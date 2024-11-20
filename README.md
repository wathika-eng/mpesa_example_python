## Getting started

1. Clone the repository

```bash
git clone https://github.com/wathika-eng/mpesa_example_python --depth 1 && cd mpesa_example_python
```

2. Activate virtualenv and nstall the dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Copy and update the environment variables

```bash
cp .env.example .env
```

4. Run the application

```bash
python mpesa.py
```
