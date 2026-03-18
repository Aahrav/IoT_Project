## Explainable GenAI Predictive Maintenance (Streamlit + RAG)

This is a free, local-first MVP for an **Explainable Generative AI-Driven Predictive Maintenance System**:

- **Predictive maintenance**: anomaly/risk scoring from IoT telemetry
- **Explainability**: what changed + which signals contributed
- **Generative AI copilot**: generates an evidence-grounded maintenance work order using **RAG** over uploaded manuals/tickets
- **Free**: runs locally with **Ollama** (optional OpenRouter later)

### 1) Prerequisites

- Windows 10/11
- Python 3.10+ (3.11 recommended)
- (Recommended) NVIDIA GPU drivers for RTX 4050
- Ollama installed (for local LLM)

### 2) Install Ollama and pull a model

1. Install Ollama: download from `https://ollama.com/`
2. Pull a small instruct model (example):

```bash
ollama pull llama3.2:3b
```

### 3) Setup Python environment

From this folder:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 4) Run the app

```bash
streamlit run app.py
```

### 5) What to do in the UI

- Go to **Data** and generate sample telemetry
- Or choose **NASA C-MAPSS** and upload the dataset files
- Go to **Docs** and upload a PDF/manual or text tickets (or use provided samples)
- Click **Build/Refresh Index**
- Pick a device + anomaly event and click **Generate Work Order**

### Using NASA C-MAPSS (real dataset)

1. Download the C-MAPSS dataset (splits like FD001..FD004).
2. Put the following files into `data/cmapss/` (or upload in the app):

- `train_FD001.txt`
- `test_FD001.txt`
- `RUL_FD001.txt`

You can also use FD002/FD003/FD004 similarly.

In the app:
- Data tab → Source: **NASA C-MAPSS**
- Choose split (FD001...) and whether to use train/test/all
- Pick which sensors (`s1..s21`) to use for anomaly scoring/plots

### Notes

- If Ollama is not running, the app still works up to retrieval; generation will show an actionable error.
- This MVP uses **unsupervised anomaly detection** (Isolation Forest) so you don’t need labeled failures.

