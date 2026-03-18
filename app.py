from __future__ import annotations

import textwrap
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.anomaly import AnomalyConfig, DEFAULT_FEATURE_COLS, fit_score_isolation_forest
from src.cmapss import detect_splits, load_split_all
from src.config import get_paths
from src.data_simulator import SimConfig, generate_telemetry
from src.llm import LlmError, generate_with_ollama, generate_with_openrouter
from src.rag import DEFAULT_EMBED_MODEL, build_index, format_citations, load_docs_from_dir, load_index, retrieve, save_index


st.set_page_config(page_title="GenAI Predictive Maintenance (RAG + Anomaly)", layout="wide")

paths = get_paths()
paths.data_dir.mkdir(parents=True, exist_ok=True)
paths.docs_dir.mkdir(parents=True, exist_ok=True)
paths.index_dir.mkdir(parents=True, exist_ok=True)


def _ui_inject_css() -> None:
    st.markdown(
        """
<style>
  .block-container { padding-top: 1.15rem; padding-bottom: 2.2rem; }
  [data-testid="stSidebar"] { border-right: 1px solid rgba(255,255,255,.08); }
  h1, h2, h3 { letter-spacing: -0.02em; }
  .pm-card {
    border: 1px solid rgba(255,255,255,.12);
    background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
    border-radius: 16px;
    padding: 14px 14px;
  }
  .pm-card .k { font-size: .8rem; opacity: .75; }
  .pm-card .v { font-size: 1.25rem; font-weight: 650; margin-top: .1rem; }
  .pm-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: .78rem;
    border: 1px solid rgba(255,255,255,.16);
    opacity: .95;
  }
  .pm-badge.ok { background: rgba(34,197,94,.15); border-color: rgba(34,197,94,.35); }
  .pm-badge.warn { background: rgba(245,158,11,.15); border-color: rgba(245,158,11,.35); }
  .pm-badge.crit { background: rgba(239,68,68,.15); border-color: rgba(239,68,68,.35); }
  .pm-evidence {
    border-left: 4px solid rgba(59,130,246,.65);
    padding: 10px 12px;
    border-radius: 12px;
    background: rgba(59,130,246,.08);
    margin-bottom: 10px;
  }
  .pm-evidence .src { font-size: .8rem; opacity: .75; }
  .pm-evidence .txt { font-size: .9rem; line-height: 1.35rem; white-space: pre-wrap; }
  .pm-workorder {
    border: 1px solid rgba(255,255,255,.12);
    border-radius: 16px;
    padding: 14px 14px;
    background: rgba(255,255,255,.03);
  }
</style>
        """,
        unsafe_allow_html=True,
    )


def _card(k: str, v: str, *, badge: str | None = None, badge_kind: str = "ok") -> None:
    badge_html = ""
    if badge:
        badge_html = f' <span class="pm-badge {badge_kind}">{badge}</span>'
    st.markdown(
        f"""
<div class="pm-card">
  <div class="k">{k}{badge_html}</div>
  <div class="v">{v}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def _risk_badge_from_score(score: float, *, p90: float, p98: float) -> tuple[str, str]:
    if score >= p98:
        return ("CRITICAL", "crit")
    if score >= p90:
        return ("WARNING", "warn")
    return ("OK", "ok")


def _load_simulated_or_make() -> pd.DataFrame:
    p = paths.data_dir / "telemetry.csv"
    if p.exists():
        return pd.read_csv(p, parse_dates=["timestamp"])
    df = generate_telemetry(SimConfig())
    df.to_csv(p, index=False)
    return df


def _load_cmapss(*, cmapss_dir: Path, split_name: str, set_filter: str) -> pd.DataFrame | None:
    """
    Expects NASA C-MAPSS files inside cmapss_dir:
      - train_FD001.txt, test_FD001.txt, RUL_FD001.txt (etc)
    Returns a dataframe with:
      - timestamp, device_id
      - sensor columns (s1..s21 + op_set_*)
      - rul (only for test; NaN for train)
    """
    splits = {s.name: s for s in detect_splits(cmapss_dir)}
    if split_name not in splits:
        return None
    df = load_split_all(splits[split_name])
    if set_filter in {"train", "test"}:
        df = df[df["set"] == set_filter].copy()

    # Convert unit/cycle into a timestamp for plotting.
    # (C-MAPSS doesn't include timestamps; we synthesize a consistent timeline.)
    df["timestamp"] = pd.Timestamp.now(tz="UTC").floor("min") + pd.to_timedelta(df["cycle"].astype(int), unit="h")
    df["device_id"] = df["unit"].map(lambda u: f"engine-{int(u):03d}")
    return df


def _save_uploaded_files(uploaded, target_dir: Path) -> list[str]:
    saved: list[str] = []
    for f in uploaded:
        out = target_dir / f.name
        out.write_bytes(f.getvalue())
        saved.append(str(out))
    return saved


def _prompt_for_work_order(*, device_id: str, row: pd.Series, citations: str, feature_cols: list[str]) -> str:
    contrib = {c: float(row.get(f"contrib_{c}", 0.0)) for c in feature_cols}
    top = sorted(contrib.items(), key=lambda x: x[1], reverse=True)[:5]
    top_str = ", ".join([f"{k} ({v:.3f})" for k, v in top])

    latest_lines = "\n".join([f"- {c}: {float(row[c]):.4g}" for c in feature_cols])

    # Keep it structured so it looks “project-worthy”.
    return f"""
You are generating a maintenance work order for an IoT device.

Rules:
- ONLY use information supported by the citations section.
- If citations are insufficient, say what is missing and propose safe diagnostic steps.
- Include citations like [1], [2] referencing the provided snippets.
- Keep the output concise, structured, and actionable.

Device: {device_id}
Timestamp: {row['timestamp']}
Anomaly score: {float(row['anomaly_score']):.4f}
Top contributing signals (proxy): {top_str}
Latest telemetry:
{latest_lines}

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

_ui_inject_css()

st.markdown("## Explainable GenAI Predictive Maintenance")
st.caption("Anomaly detection + RAG evidence + AI-generated maintenance work orders (local-first, free).")

with st.sidebar:
    st.markdown("## Controls")
    contamination = st.slider("Anomaly sensitivity (contamination)", 0.01, 0.12, 0.03, 0.005)
    k_retrieve = st.slider("RAG top-k chunks", 3, 10, 5, 1)
    embed_model = st.text_input("Embedding model", value=DEFAULT_EMBED_MODEL)

    st.markdown("### LLM")
    llm_provider = st.radio("Provider", ["Ollama (local)", "OpenRouter (optional)"], index=0)
    ollama_model = st.text_input("Ollama model", value="llama3.2:3b")
    openrouter_model = st.text_input("OpenRouter model", value="(set if using OpenRouter)")
    openrouter_key = st.text_input("OPENROUTER_API_KEY", value="", type="password")

    st.markdown("---")
    st.markdown("### Demo tips")
    st.caption(
        "- Add PDFs/tickets in **Docs** → Build index\n"
        "- Pick a device + anomaly in **Dashboard**\n"
        "- Generate a work order with citations"
    )

tab_data, tab_docs, tab_dashboard = st.tabs(["📈 Data", "📚 Docs", "🧠 Dashboard"])

with tab_data:
    st.markdown("### Telemetry dataset")
    dataset = st.segmented_control(
        "Source",
        options=["Simulated", "NASA C-MAPSS"],
        default="Simulated",
        help="Choose simulated data or load NASA C-MAPSS (turbofan) dataset files.",
    )

    if "dataset_source" not in st.session_state:
        st.session_state.dataset_source = dataset
    else:
        st.session_state.dataset_source = dataset

    if dataset == "Simulated":
        colA, colB = st.columns([1, 1])
        with colA:
            if st.button("Generate fresh sample telemetry"):
                df_new = generate_telemetry(SimConfig())
                (paths.data_dir / "telemetry.csv").write_text(df_new.to_csv(index=False), encoding="utf-8")
                st.success("Generated `data/telemetry.csv`.")
        with colB:
            st.caption("You can also replace `data/telemetry.csv` with your own data (same columns).")
        df = _load_simulated_or_make()
        feature_cols = DEFAULT_FEATURE_COLS
        source_label = "data/telemetry.csv"
    else:
        cmapss_dir = paths.data_dir / "cmapss"
        cmapss_dir.mkdir(parents=True, exist_ok=True)
        st.caption("Upload `train_FD00x.txt`, `test_FD00x.txt`, and `RUL_FD00x.txt` into `data/cmapss/` (or upload below).")

        uploaded = st.file_uploader(
            "Upload C-MAPSS files",
            type=["txt"],
            accept_multiple_files=True,
            help="You need train_*.txt, test_*.txt and RUL_*.txt for at least one split (FD001..FD004).",
        )
        if uploaded:
            saved = _save_uploaded_files(uploaded, cmapss_dir)
            st.success(f"Saved {len(saved)} file(s) into `data/cmapss/`.")

        splits = detect_splits(cmapss_dir)
        if not splits:
            st.warning("No complete split found yet. Add files like `train_FD001.txt`, `test_FD001.txt`, `RUL_FD001.txt`.")
            st.stop()

        split_name = st.selectbox("Split", [s.name for s in splits], index=0)
        set_filter = st.radio("Use", ["train", "test", "all"], index=0, horizontal=True)
        df = _load_cmapss(cmapss_dir=cmapss_dir, split_name=split_name, set_filter=set_filter)
        if df is None:
            st.error("Failed to load C-MAPSS split.")
            st.stop()

        candidate_features = [c for c in df.columns if c.startswith("s") or c.startswith("op_set_")]
        default_feats = [c for c in ["s2", "s3", "s4"] if c in candidate_features]
        feature_cols = st.multiselect("Sensors to use", candidate_features, default=default_feats or candidate_features[:3])
        if not feature_cols:
            st.error("Select at least 1 sensor feature.")
            st.stop()
        source_label = f"data/cmapss/{split_name} ({set_filter})"

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        _card("Rows", f"{len(df):,}")
    with kpi2:
        _card("Devices", f"{df['device_id'].nunique():,}")
    with kpi3:
        _card("Sensors", f"{len(feature_cols)}")
    with kpi4:
        _card("Source", source_label)

    with st.expander("Preview (first 50 rows)", expanded=False):
        st.dataframe(df.head(50), width="stretch")

    st.session_state.active_df = df
    st.session_state.active_feature_cols = feature_cols

with tab_docs:
    st.markdown("### Documents for RAG (manuals, SOPs, past tickets)")
    st.caption("Supported: `.txt`, `.md`, `.pdf`. These documents become the knowledge base for citations.")

    uploaded = st.file_uploader("Upload docs", type=["txt", "md", "pdf"], accept_multiple_files=True)
    if uploaded:
        saved = _save_uploaded_files(uploaded, paths.docs_dir)
        st.success(f"Saved {len(saved)} file(s) into `docs/`.")

    docs_list = sorted([str(p.relative_to(paths.root)) for p in paths.docs_dir.glob("**/*") if p.is_file()])
    c1, c2 = st.columns([1.6, 1])
    with c1:
        st.markdown("#### Current docs")
        st.code("\n".join(docs_list) if docs_list else "(none)")
    with c2:
        st.markdown("#### Index status")
        idx_loaded = load_index(paths.index_dir)
        if idx_loaded and idx_loaded.chunks:
            _card("Chunks indexed", f"{len(idx_loaded.chunks):,}", badge="READY", badge_kind="ok")
            _card("Embedding model", idx_loaded.embed_model_name)
        else:
            _card("Chunks indexed", "0", badge="NOT BUILT", badge_kind="warn")
            st.caption("Build the index to enable citations.")

    if st.button("Build / Refresh RAG index"):
        chunks = load_docs_from_dir(paths.docs_dir)
        idx = build_index(chunks, embed_model_name=embed_model)
        save_index(idx, paths.index_dir)
        st.success(f"Indexed {len(chunks)} chunks into `index/` using `{embed_model}`.")

with tab_dashboard:
    st.markdown("### Dashboard")
    df = st.session_state.get("active_df")
    feature_cols = st.session_state.get("active_feature_cols")
    if df is None or feature_cols is None:
        # Default fallback
        df = _load_simulated_or_make()
        feature_cols = DEFAULT_FEATURE_COLS

    missing = [c for c in (["timestamp", "device_id"] + list(feature_cols)) if c not in df.columns]
    if missing:
        st.error(f"Telemetry CSV missing columns: {missing}")
        st.stop()

    scored = fit_score_isolation_forest(df, AnomalyConfig(contamination=contamination), feature_cols=list(feature_cols))

    p90 = float(scored["anomaly_score"].quantile(0.90))
    p98 = float(scored["anomaly_score"].quantile(0.98))
    total_anoms = int(scored["anomaly_flag"].sum())

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        _card("Total anomalies", f"{total_anoms:,}")
    with k2:
        _card("P90 score", f"{p90:.3f}")
    with k3:
        _card("P98 score", f"{p98:.3f}")
    with k4:
        _card("LLM mode", llm_provider)

    left, right = st.columns([1.4, 1])
    with left:
        device = st.selectbox("Device", sorted(scored["device_id"].unique()))
        sub = scored[scored["device_id"] == device].sort_values("timestamp")

        latest = sub.iloc[-1]
        badge, badge_kind = _risk_badge_from_score(float(latest["anomaly_score"]), p90=p90, p98=p98)
        m1, m2, m3, m4 = st.columns(4)
        cols_for_cards = list(feature_cols)[:3]
        with m1:
            _card(f"Latest {cols_for_cards[0]}", f"{float(latest[cols_for_cards[0]]):.4g}")
        with m2:
            if len(cols_for_cards) > 1:
                _card(f"Latest {cols_for_cards[1]}", f"{float(latest[cols_for_cards[1]]):.4g}")
            else:
                _card("Latest", "—")
        with m3:
            if len(cols_for_cards) > 2:
                _card(f"Latest {cols_for_cards[2]}", f"{float(latest[cols_for_cards[2]]):.4g}")
            else:
                _card("Latest", "—")
        with m4:
            _card("Latest status", f"{float(latest['anomaly_score']):.3f}", badge=badge, badge_kind=badge_kind)

        fig = px.line(
            sub,
            x="timestamp",
            y=list(feature_cols),
            title="Telemetry",
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

        fig2 = px.line(sub, x="timestamp", y="anomaly_score", title="Anomaly score (higher = more abnormal)")
        fig2.add_hline(y=p90, line_dash="dot", line_color="orange", annotation_text="P90", annotation_position="top left")
        fig2.add_hline(y=p98, line_dash="dot", line_color="red", annotation_text="P98", annotation_position="top left")
        st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})

        anoms = sub[sub["anomaly_flag"] == 1].sort_values("anomaly_score", ascending=False).head(20)
        st.markdown("#### Top anomaly events")
        st.caption("Select one row to generate an evidence-grounded work order.")
        sel = st.dataframe(
            anoms[["timestamp", *list(feature_cols), "anomaly_score", "anomaly_flag"]],
            width="stretch",
            selection_mode="single-row",
            on_select="rerun",
        )

    with right:
        st.markdown("#### Investigation panel")
        if "selection" in sel and sel["selection"]["rows"]:
            idx_row = sel["selection"]["rows"][0]
            chosen = anoms.iloc[idx_row]
        else:
            chosen = sub.sort_values("anomaly_score", ascending=False).iloc[0]

        chosen_score = float(chosen["anomaly_score"])
        badge, badge_kind = _risk_badge_from_score(chosen_score, p90=p90, p98=p98)
        st.markdown(
            f"**Selected event**  <span class='pm-badge {badge_kind}'>{badge}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Timestamp: {chosen['timestamp']}  •  Score: {chosen_score:.4f}")

        contrib_cols = [f"contrib_{c}" for c in feature_cols]
        contrib_view = pd.DataFrame(
            {"feature": list(feature_cols), "contribution": [float(chosen[c]) for c in contrib_cols]}
        ).sort_values("contribution", ascending=False)
        figc = go.Figure(
            data=[
                go.Bar(
                    x=contrib_view["contribution"],
                    y=contrib_view["feature"],
                    orientation="h",
                    marker_color="rgba(59,130,246,.75)",
                )
            ]
        )
        figc.update_layout(height=230, margin=dict(l=8, r=8, t=10, b=10), xaxis_title="Contribution (proxy)", yaxis_title="")
        st.markdown("##### What contributed most (proxy)")
        st.plotly_chart(figc, width="stretch", config={"displayModeBar": False})

        st.markdown("#### Evidence (RAG)")
        idx_loaded = load_index(paths.index_dir)
        if not idx_loaded:
            st.warning("No RAG index found. Go to **Docs** and click **Build / Refresh RAG index**.")
            retrieved = []
        else:
            sample = ", ".join([f"{c}={float(chosen[c]):.4g}" for c in feature_cols[:5]])
            query = f"{device} abnormal telemetry: {sample}. Provide likely causes and checks."
            retrieved = retrieve(idx_loaded, query, k=k_retrieve)
            st.caption("Top retrieved snippets (these should be cited in the work order):")
            for i, r in enumerate(retrieved, start=1):
                src = Path(r.chunk.source).name
                snippet = textwrap.shorten(r.chunk.text.replace("\n", " "), width=520, placeholder="…")
                st.markdown(
                    f"""
<div class="pm-evidence">
  <div class="src"><b>[{i}]</b> {src} • score={r.score:.3f}</div>
  <div class="txt">{snippet}</div>
</div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("#### Work order generator")
        citations = format_citations(retrieved)
        prompt = _prompt_for_work_order(
            device_id=device,
            row=chosen,
            citations=citations or "(no citations available)",
            feature_cols=list(feature_cols),
        )

        if "work_order_text" not in st.session_state:
            st.session_state.work_order_text = ""
            st.session_state.work_order_provider = ""

        cta1, cta2 = st.columns([1, 1])
        with cta1:
            generate_clicked = st.button("Generate work order", type="primary", width="stretch")
        with cta2:
            st.download_button(
                "Download (.txt)",
                data=(st.session_state.work_order_text or "").encode("utf-8"),
                file_name=f"work_order_{device}.txt",
                mime="text/plain",
                disabled=not bool(st.session_state.work_order_text),
                use_container_width=True,
            )

        if generate_clicked:
            if llm_provider.startswith("Ollama"):
                try:
                    res = generate_with_ollama(prompt, model=ollama_model)
                    st.session_state.work_order_text = res.text
                    st.session_state.work_order_provider = res.provider
                except LlmError as e:
                    st.error(str(e))
                    st.caption("Tip: open a terminal and run `ollama serve` (or open the Ollama app), then `ollama pull llama3.2:3b`.")
            else:
                try:
                    res = generate_with_openrouter(prompt, model=openrouter_model, api_key=openrouter_key or None)
                    st.session_state.work_order_text = res.text
                    st.session_state.work_order_provider = res.provider
                except LlmError as e:
                    st.error(str(e))
                    st.caption("If OpenRouter fails (quota/rate-limit), switch back to Ollama for fully-free demo reliability.")

        if st.session_state.work_order_text:
            st.markdown(
                f"<div class='pm-workorder'><span class='pm-badge ok'>Generated via {st.session_state.work_order_provider}</span><br><br>{st.session_state.work_order_text}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Generate a work order to see the structured action plan here.")

        with st.expander("Show prompt (for debugging)"):
            st.code(prompt)

