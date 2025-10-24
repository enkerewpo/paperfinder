# format the code under the pfdr package

if ! command -v ruff &> /dev/null; then
    echo "ruff could not be found, please install it with 'pip install ruff'"
    exit 1
fi


if [ -d "pfdr" ]; then
    echo "Formatting code with ruff..."
    ruff format pfdr
    echo "Code formatting complete!"
else
    echo "pfdr directory not found"
    exit 1
fi