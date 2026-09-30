# Pseudo Set Up 🫱🐟

AKA infinite set up suite

Help you answer your boss's question "why you stopped working?"

## Python

Copy `python/install.py` into a project, activate its virtual environment, and run:

```powershell
python .\install.py
```
Override the detected environment only when needed:

```powershell
python .\install.py --python 3.12
python .\install.py --python 3.12 --pip 25.1
python .\install.py --python 3.14 --pip 26.0.1
```

## JavaScript (npm)

Copy `javascript/install.js` into a project and run it with Node.js 18+ and npm 9+:

```powershell
node .\install.js
```

The script detects the installed Node.js and npm versions. Override either version,
or enable per-package npm-style logs, with:

```powershell
node .\install.js --node 22.9.0 --npm 11.0.0
node .\install.js --verbose
node .\install.js --help
```

The default output is concise; `--verbose` shows dependency resolution, cache
hits and simulated registry fetches.
