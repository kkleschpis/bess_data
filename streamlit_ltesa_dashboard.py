"""
Streamlit dashboard: LTESA / floor / toll revenue distribution analysis

Run locally:
    pip install -r requirements.txt
    streamlit run streamlit_ltesa_dashboard.py

Units:
Use one consistent annual revenue unit throughout, e.g. AUDm/year, AUDk/MW-year,
or AUD/MW-year. The dashboard does not convert units.

Core cases:
1. Merchant-only revenue
2. Merchant revenue + net LTESA payment
3. Merchant revenue with a revenue floor
4. Partial toll + residual merchant exposure

Important simplification:
This is a single-year distribution tool. For a full multi-year LTESA valuation,
the cumulative historical net payments cap should be tracked year-by-year.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


DistributionName = Literal["normal", "lognormal", "triangular"]


@dataclass
class RevenueInputs:
    mean: float
    std: float
    distribution: DistributionName
    n_sims: int
    seed: int
    clip_at_zero: bool

    triangular_min: Optional[float] = None
    triangular_mode: Optional[float] = None
    triangular_max: Optional[float] = None

    annuity_cap: float = 100.0
    net_revenue_threshold: float = 300.0
    ltesa_sharing_pct: float = 0.50
    opening_cumulative_net_payments_cap: float = 1e12

    floor_value: float = 100.0

    toll_value: float = 200.0
    toll_share: float = 0.50

    unit_label: str = "AUDm/year"
    bins: int = 100


def simulate_merchant_revenue(inputs: RevenueInputs) -> np.ndarray:
    """Generate annual merchant revenue samples."""

    rng = np.random.default_rng(inputs.seed)

    if inputs.distribution == "normal":
        revenue = rng.normal(inputs.mean, inputs.std, inputs.n_sims)

    elif inputs.distribution == "lognormal":
        if inputs.mean <= 0:
            raise ValueError("Lognormal distribution requires mean > 0.")

        variance = inputs.std**2
        sigma2 = np.log(1 + variance / inputs.mean**2)
        sigma = np.sqrt(sigma2)
        mu = np.log(inputs.mean) - 0.5 * sigma2
        revenue = rng.lognormal(mean=mu, sigma=sigma, size=inputs.n_sims)

    elif inputs.distribution == "triangular":
        if None in (inputs.triangular_min, inputs.triangular_mode, inputs.triangular_max):
            raise ValueError("Triangular distribution requires min, mode and max.")
        revenue = rng.triangular(
            inputs.triangular_min,
            inputs.triangular_mode,
            inputs.triangular_max,
            inputs.n_sims,
        )

    else:
        raise ValueError(f"Unsupported distribution: {inputs.distribution}")

    if inputs.clip_at_zero:
        revenue = np.maximum(revenue, 0)

    return revenue


def calculate_ltesa_case(
    merchant_revenue: np.ndarray,
    annuity_cap: float,
    net_revenue_threshold: float,
    sharing_pct: float,
    opening_cumulative_net_payments_cap: float,
) -> dict[str, np.ndarray]:
    """
    Calculate annual LTESA support / repayment.

    Adjusted annuity amount:
        AAA = max(0, min(AC, AC - 75% * (NOR - (NRT - AC))))

    Annual revenue sharing / repayment:
        ARS = min(max(0, sharing_pct * (NOR - NRT)), opening cumulative net payments cap)

    Net LTESA payment:
        Net LTESA = AAA - ARS
    """

    nor = merchant_revenue
    ac = annuity_cap
    nrt = net_revenue_threshold

    adjusted_annuity_amount = np.maximum(
        0,
        np.minimum(
            ac,
            ac - 0.75 * (nor - (nrt - ac)),
        ),
    )

    annual_revenue_sharing = np.minimum(
        np.maximum(0, sharing_pct * (nor - nrt)),
        opening_cumulative_net_payments_cap,
    )

    net_ltesa_payment = adjusted_annuity_amount - annual_revenue_sharing
    revenue_with_ltesa = nor + net_ltesa_payment

    return {
        "adjusted_annuity_amount": adjusted_annuity_amount,
        "annual_revenue_sharing": annual_revenue_sharing,
        "net_ltesa_payment": net_ltesa_payment,
        "revenue_with_ltesa": revenue_with_ltesa,
    }


@st.cache_data(show_spinner=False)
def calculate_cases_cached(
    mean: float,
    std: float,
    distribution: str,
    n_sims: int,
    seed: int,
    clip_at_zero: bool,
    triangular_min: Optional[float],
    triangular_mode: Optional[float],
    triangular_max: Optional[float],
    annuity_cap: float,
    net_revenue_threshold: float,
    ltesa_sharing_pct: float,
    opening_cumulative_net_payments_cap: float,
    floor_value: float,
    toll_value: float,
    toll_share: float,
    unit_label: str,
    bins: int,
) -> pd.DataFrame:
    """Cached wrapper so the dashboard remains responsive."""

    inputs = RevenueInputs(
        mean=mean,
        std=std,
        distribution=distribution,  # type: ignore[arg-type]
        n_sims=n_sims,
        seed=seed,
        clip_at_zero=clip_at_zero,
        triangular_min=triangular_min,
        triangular_mode=triangular_mode,
        triangular_max=triangular_max,
        annuity_cap=annuity_cap,
        net_revenue_threshold=net_revenue_threshold,
        ltesa_sharing_pct=ltesa_sharing_pct,
        opening_cumulative_net_payments_cap=opening_cumulative_net_payments_cap,
        floor_value=floor_value,
        toll_value=toll_value,
        toll_share=toll_share,
        unit_label=unit_label,
        bins=bins,
    )

    merchant = simulate_merchant_revenue(inputs)

    ltesa = calculate_ltesa_case(
        merchant_revenue=merchant,
        annuity_cap=inputs.annuity_cap,
        net_revenue_threshold=inputs.net_revenue_threshold,
        sharing_pct=inputs.ltesa_sharing_pct,
        opening_cumulative_net_payments_cap=inputs.opening_cumulative_net_payments_cap,
    )

    floor_case = np.maximum(merchant, inputs.floor_value)

    toll_plus_merchant = (
        inputs.toll_share * inputs.toll_value
        + (1 - inputs.toll_share) * merchant
    )

    df = pd.DataFrame(
        {
            "Merchant": merchant,
            "LTESA": ltesa["revenue_with_ltesa"],
            "Floor": floor_case,
            "Toll + merchant": toll_plus_merchant,
            "LTESA adjusted annuity amount": ltesa["adjusted_annuity_amount"],
            "LTESA annual revenue sharing": ltesa["annual_revenue_sharing"],
            "LTESA net payment": ltesa["net_ltesa_payment"],
            "Floor payment": floor_case - merchant,
            "Toll contracted revenue": inputs.toll_share * inputs.toll_value,
            "Toll residual merchant revenue": (1 - inputs.toll_share) * merchant,
        }
    )

    return df


def expected_shortfall(values: pd.Series, percentile: float = 10) -> float:
    cutoff = np.percentile(values, percentile)
    downside_values = values[values <= cutoff]
    return float(downside_values.mean())


def build_metrics(df: pd.DataFrame, floor_value: float, toll_share: float, toll_value: float) -> pd.DataFrame:
    case_cols = ["Merchant", "LTESA", "Floor", "Toll + merchant"]

    merchant_mean = df["Merchant"].mean()
    merchant_std = df["Merchant"].std()
    merchant_p10 = np.percentile(df["Merchant"], 10)

    rows = []

    for case in case_cols:
        series = df[case]
        mean = series.mean()
        std = series.std()
        p10 = np.percentile(series, 10)

        rows.append(
            {
                "Case": case,
                "Mean revenue": mean,
                "Median revenue": np.percentile(series, 50),
                "P5 revenue": np.percentile(series, 5),
                "P10 revenue": p10,
                "P90 revenue": np.percentile(series, 90),
                "P95 revenue": np.percentile(series, 95),
                "Std dev": std,
                "Coeff. of variation": std / mean if mean else np.nan,
                "Expected shortfall P10": expected_shortfall(series, 10),
                f"Probability below {floor_value:,.1f}": (series < floor_value).mean(),
                "Mean uplift vs merchant": mean - merchant_mean,
                "P10 uplift vs merchant": p10 - merchant_p10,
                "Volatility reduction vs merchant": merchant_std - std,
            }
        )

    metrics = pd.DataFrame(rows).set_index("Case")

    metrics.loc["LTESA", "Expected LTESA net payment"] = df["LTESA net payment"].mean()
    metrics.loc["LTESA", "Expected LTESA support / AAA"] = df["LTESA adjusted annuity amount"].mean()
    metrics.loc["LTESA", "Expected LTESA repayment / sharing"] = df["LTESA annual revenue sharing"].mean()
    metrics.loc["LTESA", "Probability of LTESA support"] = (df["LTESA adjusted annuity amount"] > 0).mean()
    metrics.loc["LTESA", "Probability of LTESA repayment"] = (df["LTESA annual revenue sharing"] > 0).mean()

    metrics.loc["Floor", "Expected floor payment"] = df["Floor payment"].mean()
    metrics.loc["Floor", "Probability floor is in the money"] = (df["Floor payment"] > 0).mean()

    metrics.loc["Toll + merchant", "Contracted revenue share"] = toll_share
    metrics.loc["Toll + merchant", "Expected contracted toll revenue"] = toll_share * toll_value
    metrics.loc["Toll + merchant", "Expected residual merchant revenue"] = df["Toll residual merchant revenue"].mean()

    return metrics


def format_metric_table(metrics: pd.DataFrame) -> pd.DataFrame:
    formatted = metrics.copy()

    pct_rows = [
        col
        for col in formatted.columns
        if "Probability" in col or "share" in col or "Coeff." in col
    ]

    for col in formatted.columns:
        if col in pct_rows:
            formatted[col] = formatted[col].map(lambda x: "" if pd.isna(x) else f"{x:.1%}")
        else:
            formatted[col] = formatted[col].map(lambda x: "" if pd.isna(x) else f"{x:,.2f}")

    return formatted


def build_distribution_figure(df: pd.DataFrame, unit_label: str, bins: int) -> go.Figure:
    cases = ["Merchant", "LTESA", "Floor", "Toll + merchant"]

    combined = pd.concat([df[c] for c in cases])
    x_min = combined.min()
    x_max = combined.max()
    bin_size = (x_max - x_min) / bins if x_max > x_min else 1

    fig = make_subplots(
        rows=1,
        cols=4,
        subplot_titles=cases,
        shared_yaxes=True,
        horizontal_spacing=0.035,
    )

    for i, case in enumerate(cases, start=1):
        values = df[case]

        fig.add_trace(
            go.Histogram(
                x=values,
                histnorm="probability density",
                xbins=dict(start=x_min, end=x_max, size=bin_size),
                name=case,
                showlegend=False,
                opacity=0.80,
                hovertemplate=f"{case}<br>{unit_label}: %{{x:,.2f}}<br>Density: %{{y:.4f}}<extra></extra>",
            ),
            row=1,
            col=i,
        )

        mean = values.mean()
        p10 = np.percentile(values, 10)
        median = np.percentile(values, 50)

        axis_suffix = "" if i == 1 else str(i)
        xref = f"x{axis_suffix}"
        yref = f"y{axis_suffix} domain"

        for x_value, dash, label in [
            (mean, "dash", "Mean"),
            (p10, "dot", "P10"),
            (median, "dashdot", "P50"),
        ]:
            fig.add_shape(
                type="line",
                x0=x_value,
                x1=x_value,
                y0=0,
                y1=1,
                xref=xref,
                yref=yref,
                line=dict(width=1.5, dash=dash),
            )

        fig.add_annotation(
            x=mean,
            y=1.02,
            xref=xref,
            yref=yref,
            text="Mean",
            showarrow=False,
            font=dict(size=10),
        )

    fig.update_layout(
        height=460,
        bargap=0.02,
        margin=dict(l=20, r=20, t=60, b=30),
    )

    fig.update_xaxes(title_text=unit_label)
    fig.update_yaxes(title_text="Probability density", row=1, col=1)

    return fig


def build_cdf_figure(df: pd.DataFrame, unit_label: str) -> go.Figure:
    cases = ["Merchant", "LTESA", "Floor", "Toll + merchant"]

    fig = go.Figure()

    for case in cases:
        values = np.sort(df[case].to_numpy())
        probs = np.linspace(0, 1, len(values), endpoint=False)

        fig.add_trace(
            go.Scatter(
                x=values,
                y=probs,
                mode="lines",
                name=case,
                hovertemplate=f"{case}<br>{unit_label}: %{{x:,.2f}}<br>Cumulative probability: %{{y:.1%}}<extra></extra>",
            )
        )

    fig.update_layout(
        height=450,
        margin=dict(l=20, r=20, t=40, b=30),
        xaxis_title=unit_label,
        yaxis_title="Cumulative probability",
        yaxis_tickformat=".0%",
        legend_title_text="Case",
    )

    return fig


def build_uplift_figure(metrics: pd.DataFrame, unit_label: str) -> go.Figure:
    rows = metrics.reset_index()
    rows = rows[rows["Case"] != "Merchant"]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=rows["Case"],
            y=rows["Mean uplift vs merchant"],
            name="Mean uplift",
            hovertemplate="Mean uplift vs merchant<br>%{x}: %{y:,.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            x=rows["Case"],
            y=rows["P10 uplift vs merchant"],
            name="P10 uplift",
            hovertemplate="P10 uplift vs merchant<br>%{x}: %{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        barmode="group",
        height=420,
        margin=dict(l=20, r=20, t=40, b=30),
        yaxis_title=f"Uplift vs merchant ({unit_label})",
        xaxis_title="Case",
        legend_title_text="Metric",
    )

    return fig


def sidebar_inputs() -> RevenueInputs:
    with st.form("simulation_inputs"):
        st.subheader("Simulation inputs")

        with st.expander("Merchant revenue distribution", expanded=True):
            unit_label = st.text_input("Unit label", value="AUDm/year")

            distribution = st.selectbox(
                "Distribution",
                options=["normal", "lognormal", "triangular"],
                index=0,
            )

            mean = st.number_input("Mean annual revenue", min_value=0.0, value=250.0, step=10.0)
            std = st.number_input("Standard deviation", min_value=0.0, value=80.0, step=5.0)

            triangular_min = None
            triangular_mode = None
            triangular_max = None

            if distribution == "triangular":
                triangular_min = st.number_input("Triangular min", value=50.0, step=10.0)
                triangular_mode = st.number_input("Triangular mode", value=250.0, step=10.0)
                triangular_max = st.number_input("Triangular max", value=500.0, step=10.0)

                if not (triangular_min <= triangular_mode <= triangular_max):
                    st.error("Triangular inputs must satisfy min ≤ mode ≤ max.")

            clip_at_zero = st.checkbox("Clip simulated merchant revenue at zero", value=True)
            n_sims = st.slider("Number of simulations", min_value=10_000, max_value=500_000, value=100_000, step=10_000)
            seed = st.number_input("Random seed", min_value=0, value=42, step=1)

        with st.expander("LTESA", expanded=True):
            annuity_cap = st.number_input("Annuity Cap / AC", min_value=0.0, value=100.0, step=5.0)
            net_revenue_threshold = st.number_input("Net Revenue Threshold / NRT", min_value=0.0, value=300.0, step=10.0)
            ltesa_sharing_pct = st.slider("Upside sharing / repayment % above NRT", 0.0, 1.0, 0.50, 0.05)
            opening_cumulative_net_payments_cap = st.number_input(
                "Opening cumulative historical net payments cap",
                min_value=0.0,
                value=1_000_000_000.0,
                step=10.0,
                help="Use a high value for a steady-state one-year view. For a multi-year LTESA, this needs to be tracked year-by-year.",
            )

        with st.expander("Floor", expanded=True):
            floor_value = st.number_input("Floor value", min_value=0.0, value=100.0, step=5.0)

        with st.expander("Toll + residual merchant", expanded=True):
            toll_value = st.number_input(
                "Full-asset equivalent toll value",
                min_value=0.0,
                value=200.0,
                step=10.0,
            )
            toll_share = st.slider("Share of project under toll", 0.0, 1.0, 0.50, 0.05)

        with st.expander("Chart settings", expanded=False):
            bins = st.slider("Histogram bins", min_value=40, max_value=200, value=100, step=10)

        st.form_submit_button("Run simulation", type="primary")

    return RevenueInputs(
        mean=mean,
        std=std,
        distribution=distribution,  # type: ignore[arg-type]
        n_sims=n_sims,
        seed=int(seed),
        clip_at_zero=clip_at_zero,
        triangular_min=triangular_min,
        triangular_mode=triangular_mode,
        triangular_max=triangular_max,
        annuity_cap=annuity_cap,
        net_revenue_threshold=net_revenue_threshold,
        ltesa_sharing_pct=ltesa_sharing_pct,
        opening_cumulative_net_payments_cap=opening_cumulative_net_payments_cap,
        floor_value=floor_value,
        toll_value=toll_value,
        toll_share=toll_share,
        unit_label=unit_label,
        bins=bins,
    )


def show_formula_notes() -> None:
    with st.expander("Calculation notes", expanded=False):
        st.markdown(
            """
            **LTESA adjusted annuity amount**

            `AAA = MAX(0, MIN(AC, AC - 75% × (NOR - (NRT - AC))))`

            **LTESA repayment / annual revenue sharing**

            `Repayment = MIN(MAX(0, sharing % × (NOR - NRT)), opening cumulative historical net payments cap)`

            **Net LTESA payment**

            `Net LTESA = AAA - Repayment`

            **Total LTESA case revenue**

            `LTESA revenue = merchant revenue + Net LTESA`

            **Floor case**

            `Floor revenue = MAX(merchant revenue, floor value)`

            **Partial toll case**

            `Toll + merchant = toll share × full-asset toll value + (1 - toll share) × merchant revenue`
            """
        )


def main() -> None:
    st.set_page_config(
        page_title="LTESA distribution dashboard",
        page_icon="📊",
        layout="wide",
    )

    st.title("LTESA / floor / toll revenue distribution dashboard")
    st.caption(
        "Single-year Monte Carlo analysis for an Australian BESS. "
        "Use one consistent annual unit across all inputs."
    )

    inputs = sidebar_inputs()

    if inputs.distribution == "triangular":
        if not (
            inputs.triangular_min is not None
            and inputs.triangular_mode is not None
            and inputs.triangular_max is not None
            and inputs.triangular_min <= inputs.triangular_mode <= inputs.triangular_max
        ):
            st.stop()

    df = calculate_cases_cached(
        mean=inputs.mean,
        std=inputs.std,
        distribution=inputs.distribution,
        n_sims=inputs.n_sims,
        seed=inputs.seed,
        clip_at_zero=inputs.clip_at_zero,
        triangular_min=inputs.triangular_min,
        triangular_mode=inputs.triangular_mode,
        triangular_max=inputs.triangular_max,
        annuity_cap=inputs.annuity_cap,
        net_revenue_threshold=inputs.net_revenue_threshold,
        ltesa_sharing_pct=inputs.ltesa_sharing_pct,
        opening_cumulative_net_payments_cap=inputs.opening_cumulative_net_payments_cap,
        floor_value=inputs.floor_value,
        toll_value=inputs.toll_value,
        toll_share=inputs.toll_share,
        unit_label=inputs.unit_label,
        bins=inputs.bins,
    )

    metrics = build_metrics(
        df=df,
        floor_value=inputs.floor_value,
        toll_share=inputs.toll_share,
        toll_value=inputs.toll_value,
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Best mean revenue", metrics["Mean revenue"].idxmax(), f"{metrics['Mean revenue'].max():,.2f}")

    with col2:
        st.metric("Best P10 revenue", metrics["P10 revenue"].idxmax(), f"{metrics['P10 revenue'].max():,.2f}")

    with col3:
        st.metric("Lowest volatility", metrics["Std dev"].idxmin(), f"{metrics['Std dev'].min():,.2f}")

    with col4:
        st.metric("Highest expected shortfall P10", metrics["Expected shortfall P10"].idxmax(), f"{metrics['Expected shortfall P10'].max():,.2f}")

    tabs = st.tabs(["Distributions", "Cumulative risk", "Decision metrics", "Raw simulations"])

    with tabs[0]:
        st.subheader("Revenue distributions")
        st.plotly_chart(
            build_distribution_figure(df, inputs.unit_label, inputs.bins),
            use_container_width=True,
        )

        st.subheader("Mean and P10 uplift versus merchant")
        st.plotly_chart(
            build_uplift_figure(metrics, inputs.unit_label),
            use_container_width=True,
        )

    with tabs[1]:
        st.subheader("Cumulative distribution")
        st.plotly_chart(
            build_cdf_figure(df, inputs.unit_label),
            use_container_width=True,
        )

        st.info(
            "Read this as downside protection: further right is better at the same percentile. "
            "A steeper CDF means lower volatility."
        )

    with tabs[2]:
        st.subheader("Decision metrics")
        st.dataframe(format_metric_table(metrics), use_container_width=True)

        st.download_button(
            label="Download metrics as CSV",
            data=metrics.to_csv().encode("utf-8"),
            file_name="ltesa_distribution_metrics.csv",
            mime="text/csv",
        )

        show_formula_notes()

    with tabs[3]:
        st.subheader("Simulation output")
        st.dataframe(df.head(1_000), use_container_width=True)

        st.download_button(
            label="Download full simulation as CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="ltesa_distribution_simulations.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
