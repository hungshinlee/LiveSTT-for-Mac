"""
將 HuggingFace Whisper 模型轉換為 MLX 格式
支援分片 (sharded) 和單一檔案 safetensors 格式
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from huggingface_hub import snapshot_download
from safetensors import safe_open


def get_model_output_name(hf_repo: str) -> str:
    """從 HuggingFace repo 名稱取得輸出資料夾名稱"""
    # formospeech/whisper-large-v2-taiwanese-hakka-v1 -> whisper-large-v2-taiwanese-hakka-v1-mlx
    repo_name = hf_repo.split("/")[-1]
    return f"{repo_name}-mlx"


def load_safetensors(model_path: Path) -> dict:
    """載入 safetensors 權重（支援單一檔案和分片格式）"""
    weights = {}
    
    # 找出所有 safetensors 檔案
    safetensor_files = sorted(model_path.glob("*.safetensors"))
    
    # 排除 index 檔案
    safetensor_files = [f for f in safetensor_files if "index" not in f.name]
    
    if not safetensor_files:
        raise FileNotFoundError(f"找不到 safetensors 檔案: {model_path}")
    
    print(f"  找到 {len(safetensor_files)} 個權重檔案")
    
    for sf_file in safetensor_files:
        print(f"    載入: {sf_file.name}")
        with safe_open(sf_file, framework="numpy") as f:
            for key in f.keys():
                weights[key] = f.get_tensor(key)
    
    return weights


def get_mlx_config(hf_config: dict) -> dict:
    """從 HuggingFace config 建立 MLX Whisper 配置"""
    return {
        "n_mels": hf_config.get("num_mel_bins", 80),
        "n_audio_ctx": hf_config.get("max_source_positions", 1500),
        "n_audio_state": hf_config.get("d_model", 1280),
        "n_audio_head": hf_config.get("encoder_attention_heads", 20),
        "n_audio_layer": hf_config.get("encoder_layers", 32),
        "n_vocab": hf_config.get("vocab_size", 51865),
        "n_text_ctx": hf_config.get("max_target_positions", 448),
        "n_text_state": hf_config.get("d_model", 1280),
        "n_text_head": hf_config.get("decoder_attention_heads", 20),
        "n_text_layer": hf_config.get("decoder_layers", 32),
        "model_type": "whisper",
    }


def convert_key(key: str) -> str | None:
    """
    轉換 HuggingFace 權重鍵名為 MLX 格式
    返回 None 表示應該跳過這個鍵
    """
    # 移除 model. 前綴
    key = key.replace("model.", "")
    
    # 跳過 encoder 的 positional embedding（MLX 使用 sinusoidal，不需要存儲）
    if "encoder.embed_positions" in key:
        return None
    
    # decoder 的 positional embedding
    key = key.replace("decoder.embed_positions.weight", "decoder.positional_embedding")
    
    # Token embedding
    key = key.replace("decoder.embed_tokens.weight", "decoder.token_embedding.weight")
    
    # layers -> blocks
    key = key.replace(".layers.", ".blocks.")
    
    # Self attention
    key = key.replace(".self_attn.k_proj.", ".attn.key.")
    key = key.replace(".self_attn.v_proj.", ".attn.value.")
    key = key.replace(".self_attn.q_proj.", ".attn.query.")
    key = key.replace(".self_attn.out_proj.", ".attn.out.")
    
    # Cross attention (decoder only)
    key = key.replace(".encoder_attn.k_proj.", ".cross_attn.key.")
    key = key.replace(".encoder_attn.v_proj.", ".cross_attn.value.")
    key = key.replace(".encoder_attn.q_proj.", ".cross_attn.query.")
    key = key.replace(".encoder_attn.out_proj.", ".cross_attn.out.")
    
    # Layer norms
    key = key.replace(".self_attn_layer_norm.", ".attn_ln.")
    key = key.replace(".encoder_attn_layer_norm.", ".cross_attn_ln.")
    key = key.replace(".final_layer_norm.", ".mlp_ln.")
    
    # 最終的 layer norm：encoder 用 ln_post，decoder 用 ln
    key = key.replace("encoder.layer_norm.", "encoder.ln_post.")
    key = key.replace("decoder.layer_norm.", "decoder.ln.")
    
    # MLP: fc1 -> mlp1, fc2 -> mlp2 (MLX 格式)
    key = key.replace(".fc1.", ".mlp1.")
    key = key.replace(".fc2.", ".mlp2.")
    
    return key


def convert_weights(hf_weights: dict) -> dict:
    """轉換所有權重為 MLX 格式"""
    mlx_weights = {}
    skipped = []
    
    for hf_key, value in hf_weights.items():
        mlx_key = convert_key(hf_key)
        
        # 跳過不需要的鍵
        if mlx_key is None:
            skipped.append(hf_key)
            continue
        
        # Conv 權重需要轉置: (out, in, kernel) -> (out, kernel, in)
        if "conv1.weight" in mlx_key or "conv2.weight" in mlx_key:
            if len(value.shape) == 3:
                value = np.transpose(value, (0, 2, 1))
        
        mlx_weights[mlx_key] = value
    
    if skipped:
        print(f"  跳過 {len(skipped)} 個不需要的鍵")
    
    return mlx_weights


def is_model_converted(output_path: Path) -> bool:
    """檢查模型是否已經轉換過"""
    weights_file = output_path / "weights.npz"
    config_file = output_path / "config.json"
    return weights_file.exists() and config_file.exists()


def convert_model(hf_repo: str, output_dir: Path, dtype: str = "float16", force: bool = False) -> Path:
    """
    轉換 HuggingFace Whisper 模型到 MLX 格式
    
    Args:
        hf_repo: HuggingFace 模型路徑 (如 formospeech/whisper-large-v2-taiwanese-hakka-v1)
        output_dir: 輸出的父目錄 (模型會存在 output_dir/{repo-name}-mlx)
        dtype: 輸出數據類型 (float16 或 float32)
        force: 是否強制重新轉換
    
    Returns:
        轉換後模型的路徑
    """
    # 計算輸出路徑
    model_name = get_model_output_name(hf_repo)
    output_path = output_dir / model_name
    
    print(f"=== 轉換 Whisper 模型 ===")
    print(f"來源: {hf_repo}")
    print(f"輸出: {output_path}")
    print()
    
    # 檢查是否已轉換
    if not force and is_model_converted(output_path):
        print(f"✓ 模型已存在，跳過轉換")
        print(f"  (使用 --force 強制重新轉換)")
        return output_path
    
    # 下載模型
    print("步驟 1/6: 下載模型")
    model_path = Path(snapshot_download(
        repo_id=hf_repo,
        allow_patterns=["*.json", "*.safetensors", "*.txt"],
    ))
    print(f"  路徑: {model_path}")
    print()
    
    # 載入 config
    print("步驟 2/6: 載入配置")
    config_file = model_path / "config.json"
    if not config_file.exists():
        raise FileNotFoundError(f"找不到 config.json: {config_file}")
    
    with open(config_file) as f:
        hf_config = json.load(f)
    
    mlx_config = get_mlx_config(hf_config)
    print(f"  encoder layers: {mlx_config['n_audio_layer']}")
    print(f"  decoder layers: {mlx_config['n_text_layer']}")
    print(f"  model dim: {mlx_config['n_audio_state']}")
    print(f"  vocab size: {mlx_config['n_vocab']}")
    print()
    
    # 載入權重
    print("步驟 3/6: 載入權重")
    hf_weights = load_safetensors(model_path)
    print(f"  總共 {len(hf_weights)} 個張量")
    print()
    
    # 轉換權重
    print("步驟 4/6: 轉換權重格式")
    mlx_weights = convert_weights(hf_weights)
    print(f"  完成: {len(mlx_weights)} 個張量")
    print()
    
    # 轉換數據類型
    print(f"步驟 5/6: 轉換為 {dtype}")
    target_dtype = np.float16 if dtype == "float16" else np.float32
    for key in mlx_weights:
        if mlx_weights[key].dtype in [np.float32, np.float64]:
            mlx_weights[key] = mlx_weights[key].astype(target_dtype)
    print("  完成")
    print()
    
    # 保存模型
    print("步驟 6/6: 保存模型")
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 保存權重
    weights_file = output_path / "weights.npz"
    print(f"  權重: {weights_file}")
    np.savez(str(weights_file), **mlx_weights)
    
    # 保存配置
    config_out = output_path / "config.json"
    print(f"  配置: {config_out}")
    with open(config_out, "w") as f:
        json.dump(mlx_config, f, indent=2)
    
    # 計算檔案大小
    weights_size = weights_file.stat().st_size / (1024 * 1024 * 1024)
    
    print()
    print(f"=== 轉換完成！===")
    print(f"模型路徑: {output_path}")
    print(f"權重大小: {weights_size:.2f} GB")
    
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="將 HuggingFace Whisper 模型轉換為 MLX 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  # 轉換臺灣客語模型
  python convert.py formospeech/whisper-large-v2-taiwanese-hakka-v1
  
  # 轉換其他模型
  python convert.py openai/whisper-large-v3
  
  # 強制重新轉換
  python convert.py formospeech/whisper-large-v2-taiwanese-hakka-v1 --force
  
  # 使用 float32
  python convert.py formospeech/whisper-large-v2-taiwanese-hakka-v1 --dtype float32
"""
    )
    parser.add_argument(
        "hf_repo",
        type=str,
        help="HuggingFace 模型路徑 (如 formospeech/whisper-large-v2-taiwanese-hakka-v1)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="輸出目錄 (預設: ../models)",
    )
    parser.add_argument(
        "--dtype",
        type=str,
        choices=["float16", "float32"],
        default="float16",
        help="輸出數據類型 (預設: float16)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="強制重新轉換（即使模型已存在）",
    )
    
    args = parser.parse_args()
    
    # 設定輸出目錄
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        # 預設為 mlx/models
        script_dir = Path(__file__).parent
        output_dir = script_dir.parent / "models"
    
    try:
        output_path = convert_model(
            hf_repo=args.hf_repo,
            output_dir=output_dir,
            dtype=args.dtype,
            force=args.force,
        )
        
        print()
        print("使用方式:")
        print(f'  import mlx_whisper')
        print(f'  result = mlx_whisper.transcribe("audio.wav", path_or_hf_repo="{output_path}")')
        
    except Exception as e:
        print(f"\n錯誤: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
