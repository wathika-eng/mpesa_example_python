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

On line 254 in `mpesa.py` after `main()` function, replace phone number with your phone number.

```python
    try:
        mpesa_client = MPesaClient()

        # Example transaction, change as needed
        phone_number = "254746554245"
```

4. Run the application

```bash
python mpesa.py
```

## Sample output

Response: ![image](https://i.ibb.co/grSGmCk/Screenshot-From-2024-11-20-18-48-24.png)

Logs: ![sampleLogs](https://i.ibb.co/rtdJ3MR/Screenshot-From-2024-11-20-18-55-21.png)
