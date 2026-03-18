from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.anomaly import AnomalyConfig, FEATURE_COLS, fit_score_isolation_forest
from src.config import get_paths
from src.data_simulator import SimConfig, generate_telemetry
from src.llm import LlmError, generate_with_ollama, generate_with_openrouter
from src.rag import DEFAULT_EMBED_MODEL, build_index, format_citations, load_docs_from_dir, load_index, retrieve, save_index


st.set_page_config(page_title="GenAI Predictive Maintenance (RAG + Anomaly)", layout="wide")

paths = get_paths()
paths.data_dir.mkdir(parents=True, exist_ok=True)
paths.docs_dir.mkdir(parents=True, exist_ok=True)
paths.index_dir.mkdir(parents=True, exist_ok=True)


def _load_or_make_data() -> pd.DataFrame:
    p = paths.data_dir / "telemetry.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["timestamp"])
        return df
    df = generate_telemetry(SimConfig())
    df.to_csv(p, index=False)
    return df


def _save_uploaded_files(uploaded, target_dir: Path) -> list[str]:
    saved: list[str] = []
    for f in uploaded:
        out = target_dir / f.name
        out.write_bytes(f.getvalue())
        saved.append(str(out))
    return saved


def _prompt_for_work_order(*, device_id: str, row: pd.Series, citations: str) -> str:
    contrib = {
        "temperature_c": float(row.get("contrib_temperature_c", 0.0)),
        "vibration_rms": float(row.get("contrib_vibration_rms", 0.0)),
        "current_a": float(row.get("contrib_current_a", 0.0)),
    }
    top = sorted(contrib.items(), key=lambda x: x[1], reverse=True)
    top_str = ", ".join([f"{k} ({v:.3f})" for k, v in top])

    # Keep it structured so it looks “project-worthy”.
    return f"""
You are generating a maintenance work order for an IoT device.

Rules:
- ONLY use information supported by the citations section.
- If citations are insufficient, say what is missing and propose safe diagnostic steps.
- Include citations like [1], [2] referencing the provided snippets.

Device: {device_id}
Timestamp: {row['timestamp']}
Anomaly score: {float(row['anomaly_score']):.4f}
Top contributing signals (proxy): {top_str}
Latest telemetry:
- temperature_c: {float(row['temperature_c']):.2f}
- vibration_rms: {float(row['vibration_rms']):.3f}
- current_a: {float(row['current_a']):.2f}

Output format:
1) Summary (1-2 sentences)
2) Likely issue(s) with rationale (bullets)
3) Immediate safety actions (bullets)
4) Diagnostic checklist (step-by-step)
5) Recommended fix / next maintenance actions (bullets)
6) Required tools/parts (bullets)
7) Confidence (low/med/high) + what data would increase confidence

Citations:
{citations}
""".strip()


st.title("Explainable GenAI Predictive Maintenance (Anomaly + RAG Work Orders)")

with st.sidebar:
    st.header("Settings")
    contamination = st.slider("Anomaly sensitivity (contamination)", 0.01, 0.12, 0.03, 0.005)
    k_retrieve = st.slider("RAG top-k chunks", 3, 10, 5, 1)
    embed_model = st.text_input("Embedding model", value=DEFAULT_EMBED_MODEL)

    st.subheader("LLM provider")
    llm_provider = st.radio("Provider", ["Ollama (local)", "OpenRouter (optional)"], index=0)
    ollama_model = st.text_input("Ollama model", value="llama3.2:3b")
    openrouter_model = st.text_input("OpenRouter model", value="(set if using OpenRouter)")
    openrouter_key = st.text_input("OPENROUTER_API_KEY", value="", type="password")

tab_data, tab_docs, tab_dashboard = st.tabs(["Data", "Docs", "Dashboard"])

with tab_data:
    st.subheader("Telemetry dataset")
    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Generate fresh sample telemetry"):
            df_new = generate_telemetry(SimConfig())
            (paths.data_dir / "telemetry.csv").write_text(df_new.to_csv(index=False), encoding="utf-8")
            st.success("Generated `data/telemetry.csv`.")
    with colB:
        st.caption("You can also replace `data/telemetry.csv` with your own data (same columns).")

    df = _load_or_make_data()
    st.write(df.head(20))
    st.caption(f"Rows: {len(df):,} | Devices: {df['device_id'].nunique()}")

with tab_docs:
    st.subheader("Documents for RAG (manuals, SOPs, past tickets)")
    st.caption("Place documents in `docs/` or upload here. Supported: .txt, .md, .pdf")

    uploaded = st.file_uploader("Upload docs", type=["txt", "md", "pdf"], accept_multiple_files=True)
    if uploaded:
        saved = _save_uploaded_files(uploaded, paths.docs_dir)
        st.success(f"Saved {len(saved)} file(s) into `docs/`.")

    docs_list = sorted([str(p.relative_to(paths.root)) for p in paths.docs_dir.glob("**/*") if p.is_file()])
    st.write("Current docs:")
    st.code("\n".join(docs_list) if docs_list else "(none)")

    if st.button("Build / Refresh RAG index"):
        chunks = load_docs_from_dir(paths.docs_dir)
        idx = build_index(chunks, embed_model_name=embed_model)
        save_index(idx, paths.index_dir)
        st.success(f"Indexed {len(chunks)} chunks into `index/` using `{embed_model}`.")

with tab_dashboard:
    st.subheader("Anomaly scoring + explainable work order generation")
    df = _load_or_make_data()

    missing = [c for c in (["timestamp", "device_id"] + FEATURE_COLS) if c not in df.columns]
    if missing:
        st.error(f"Telemetry CSV missing columns: {missing}")
        st.stop()

    scored = fit_score_isolation_forest(df, AnomalyConfig(contamination=contamination))

    left, right = st.columns([1.25, 1])
    with left:
        device = st.selectbox("Device", sorted(scored["device_id"].unique()))
        sub = scored[scored["device_id"] == device].sort_values("timestamp")

        fig = px.line(
            sub,
            x="timestamp",
            y=FEATURE_COLS,
            title="Telemetry",
        )
        st.plotly_chart(fig, width="stretch")

        fig2 = px.line(sub, x="timestamp", y="anomaly_score", title="Anomaly score (higher = more abnormal)")
        st.plotly_chart(fig2, width="stretch")

        anoms = sub[sub["anomaly_flag"] == 1].sort_values("anomaly_score", ascending=False).head(20)
        st.write("Top anomalies (click a row below):")
        sel = st.dataframe(
            anoms[["timestamp", *FEATURE_COLS, "anomaly_score", "anomaly_flag"]],
            width="stretch",
            selection_mode="single-row",
            on_select="rerun",
        )

    with right:
        st.markdown("#### Explainability (fast proxy)")
        if "selection" in sel and sel["selection"]["rows"]:
            idx_row = sel["selection"]["rows"][0]
            chosen = anoms.iloc[idx_row]
        else:
            chosen = sub.sort_values("anomaly_score", ascending=False).iloc[0]

        st.write("Selected event:")
        st.json(
            {
                "timestamp": str(chosen["timestamp"]),
                "device_id": device,
                "temperature_c": float(chosen["temperature_c"]),
                "vibration_rms": float(chosen["vibration_rms"]),
                "current_a": float(chosen["current_a"]),
                "anomaly_score": float(chosen["anomaly_score"]),
            }
        )

        contrib_cols = [f"contrib_{c}" for c in FEATURE_COLS]
        contrib_view = pd.DataFrame(
            {"feature": FEATURE_COLS, "contribution": [float(chosen[c]) for c in contrib_cols]}
        ).sort_values("contribution", ascending=False)
        st.bar_chart(contrib_view.set_index("feature"))

        st.markdown("#### RAG evidence")
        idx_loaded = load_index(paths.index_dir)
        if not idx_loaded:
            st.warning("No RAG index found. Go to the Docs tab and click **Build / Refresh RAG index**.")
            retrieved = []
        else:
            query = f"{device} abnormal telemetry: temp={chosen['temperature_c']:.2f} vib={chosen['vibration_rms']:.3f} current={chosen['current_a']:.2f}. Provide likely causes and checks."
            retrieved = retrieve(idx_loaded, query, k=k_retrieve)
            st.caption("Top retrieved snippets:")
            for i, r in enumerate(retrieved, start=1):
                st.markdown(f"**[{i}] score={r.score:.3f}** — `{Path(r.chunk.source).name}`")
                st.code(r.chunk.text[:700] + ("…" if len(r.chunk.text) > 700 else ""))

        st.markdown("#### Generate maintenance work order")
        citations = format_citations(retrieved)
        prompt = _prompt_for_work_order(device_id=device, row=chosen, citations=citations or "(no citations available)")

        if st.button("Generate work order"):
            if llm_provider.startswith("Ollama"):
                try:
                    res = generate_with_ollama(prompt, model=ollama_model)
                    st.success(f"Generated via **{res.provider}**")
                    st.write(res.text)
                except LlmError as e:
                    st.error(str(e))
                    st.caption("Tip: open a terminal and run `ollama serve` (or open the Ollama app), then `ollama pull llama3.2:3b`.")
            else:
                try:
                    res = generate_with_openrouter(prompt, model=openrouter_model, api_key=openrouter_key or None)
                    st.success(f"Generated via **{res.provider}**")
                    st.write(res.text)
                except LlmError as e:
                    st.error(str(e))
                    st.caption("If OpenRouter fails (quota/rate-limit), switch back to Ollama for fully-free demo reliability.")

        with st.expander("Show prompt (for debugging)"):
            st.code(prompt)

