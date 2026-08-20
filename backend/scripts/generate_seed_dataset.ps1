$ErrorActionPreference = "Stop"
$generator = Join-Path $PSScriptRoot "generate_seed_dataset.py"

python $generator
if ($LASTEXITCODE -ne 0) {
    throw "Khong the tao du lieu seed RAG."
}
