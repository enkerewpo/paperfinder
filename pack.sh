# pack python package and upload to pypi
python -m build
ls -la dist/
python -m twine check dist/*
python -m twine upload dist/*