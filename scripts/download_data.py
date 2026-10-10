import sys
from pathlib import Path
from qlib.tests.data import GetData

def download_cn_data(dataset_type="qlib_data_simple"):
    target_dir = Path.home() / ".qlib" / "qlib_data" / "cn_data"
    print(f"[*] 开始下载与准备 A 股数据 [{dataset_type}] 到: {target_dir}")
    # delete_old=False, exists_skip=True
    GetData(delete_zip_file=True).qlib_data(
        name=dataset_type,
        target_dir=str(target_dir),
        region="cn",
        interval="1d",
        delete_old=False,
        exists_skip=True
    )
    print(f"[✓] 数据准备就绪: {target_dir}")

if __name__ == "__main__":
    dtype = sys.argv[1] if len(sys.argv) > 1 else "qlib_data_simple"
    download_cn_data(dtype)
