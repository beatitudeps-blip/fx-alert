"""
ウォークフォワード分析テスト（最初の5窓のみ）
"""
import os
import sys
from pathlib import Path
from run_walk_forward import run_walk_forward_analysis

sys.path.insert(0, str(Path(__file__).parent.parent))

if __name__ == "__main__":
    api_key = os.environ.get("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")

    # テスト: 最初の5窓のみ（2024-01-01 ~ 2024-09-30）
    df = run_walk_forward_analysis(
        symbols=["EUR/JPY", "USD/JPY"],  # GBP/JPYは除外（テスト時間短縮）
        start_date="2024-01-01",
        end_date="2024-09-30",  # 最初の数窓のみ
        api_key=api_key,
        initial_equity=100000.0,
        risk_pct=0.005,
        atr_mult=1.2,
        tp1_r=1.2,
        tp2_r=2.4,
        is_months=3,
        oos_months=1,
        roll_months=1
    )

    print("\n✅ ウォークフォワード分析テスト完了")
    print(f"窓数: {df['window'].nunique()}")
    print(f"結果行数: {len(df)}")
