# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('web/index.html', 'web'), ('src/s125_all.txt', 'src')],
    hiddenimports=['tavily', 'dotenv', 'openai', 'matplotlib.backends.backend_agg', 'pypdf'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide6', 'PySide2', 'torch', 'torchvision', 'torchaudio', 'nltk', 'IPython', 'jupyter', 'notebook', 'sphinx', 'jedi', 'black', 'zmq', 'vtk', 'vtkmodules', 'panel', 'bokeh', 'botocore', 'boto3', 'bitsandbytes', 'spacy', 'transformers', 'llvmlite', 'numba', 'scipy', 'pandas', 'sklearn', 'statsmodels', 'plotly', 'skimage', 'pyarrow', 'astropy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI_Scientist',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI_Scientist',
)
