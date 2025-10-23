# format the code under the pfdr package

# check black and ruff are installed
if ! command -v black &> /dev/null; then
    echo "black could not be found, please install it with 'pip install black'"
    exit 1
fi
if ! command -v ruff &> /dev/null; then
    echo "ruff could not be found, please install it with 'pip install ruff'"
    exit 1
fi


if [ -d "pfdr" ]; then
    black pfdr
else
    echo "pfdr directory not found"
    exit 1
fi