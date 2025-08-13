import asyncio
from typing import Optional

import gradio as gr
import pandas as pd
import plotly.express as px

from util import css, js, Color
from accounts import Account
from database import read_log

from trading_floor import names, lastnames, short_model_names, create_traders

from tracers import LogTracer
from agents import add_trace_processor

from market import is_market_open


# -------------------------------------------------------------------
# Color mapper for log lines
mapper = {
    "trace": Color.WHITE,
    "agent": Color.CYAN,
    "function": Color.GREEN,
    "generation": Color.YELLOW,
    "response": Color.MAGENTA,
    "account": Color.RED,
}


class Trader:
    """UI-facing trader card that reads from Account/logs."""

    def __init__(self, name: str, lastname: str, model_name: str):
        self.name = name
        self.lastname = lastname
        self.model_name = model_name
        self.account = Account.get(name)

    def reload(self):
        self.account = Account.get(self.name)

    def get_title(self) -> str:
        return (
            "<div style='text-align: center;font-size:24px;'>"
            f"{self.name}<span style='color:#ccc;font-size:16px;'> ({self.model_name}) - {self.lastname}</span>"
            "</div>"
        )

    def get_strategy(self) -> str:
        return self.account.get_strategy()

    def get_portfolio_value_df(self) -> pd.DataFrame:
        df = pd.DataFrame(
            self.account.portfolio_value_time_series, columns=["datetime", "value"]
        )
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df

    def get_portfolio_value_chart(self):
        df = self.get_portfolio_value_df()
        fig = px.line(df, x="datetime", y="value")
        margin = dict(l=40, r=20, t=20, b=40)
        fig.update_layout(
            height=250,
            margin=margin,
            xaxis_title=None,
            yaxis_title=None,
            paper_bgcolor="#bbb",
            plot_bgcolor="#dde",
        )
        fig.update_xaxes(tickformat="%m/%d", tickangle=45, tickfont=dict(size=8))
        fig.update_yaxes(tickfont=dict(size=8), tickformat=",.0f")
        return fig

    def get_holdings_df(self) -> pd.DataFrame:
        holdings = self.account.get_holdings()
        if not holdings:
            return pd.DataFrame(columns=["Symbol", "Quantity"])
        return pd.DataFrame(
            [{"Symbol": symbol, "Quantity": quantity} for symbol, quantity in holdings.items()]
        )

    def get_transactions_df(self) -> pd.DataFrame:
        transactions = self.account.list_transactions()
        if not transactions:
            return pd.DataFrame(
                columns=["Timestamp", "Symbol", "Quantity", "Price", "Rationale"]
            )
        return pd.DataFrame(transactions)

    def get_portfolio_value(self) -> str:
        portfolio_value = self.account.calculate_portfolio_value() or 0.0
        pnl = self.account.calculate_profit_loss(portfolio_value) or 0.0
        color = "green" if pnl >= 0 else "red"
        emoji = "⬆" if pnl >= 0 else "⬇"
        return (
            f"<div style='text-align: center;background-color:{color}; padding:4px;'>"
            f"<span style='font-size:24px'>${portfolio_value:,.0f}</span>"
            f"<span style='font-size:18px'>&nbsp;&nbsp;&nbsp;{emoji}&nbsp;${pnl:,.0f}</span>"
            "</div>"
        )

    def get_logs(self, previous=None) -> str:
        logs = read_log(self.name, last_n=13)
        response = ""
        for log in logs:
            timestamp, type, message = log
            color = mapper.get(type, Color.WHITE).value
            response += f"<span style='color:{color}'>{timestamp} : [{type}] {message}</span><br/>"
        response = f"<div style='height:200px; overflow-y:auto;'>{response}</div>"
        # Force update if content changed
        if response != previous:
            return response
        return gr.update()


class TraderView:
    def __init__(self, trader: Trader):
        self.trader = trader
        self.portfolio_value = None
        self.chart = None
        self.holdings_table = None
        self.transactions_table = None
        self.log = None

    def make_ui(self):
        """Render the trader card UI inside a group column for horizontal layout."""
        with gr.Group(elem_classes=["card"]):
            with gr.Column():
                gr.HTML(self.trader.get_title())

                # ✅ Initialize components with initial values, not function refs
                self.portfolio_value = gr.HTML(value=self.trader.get_portfolio_value())
                self.chart = gr.Plot(value=self.trader.get_portfolio_value_chart())
                self.log = gr.HTML(value=self.trader.get_logs())

                self.holdings_table = gr.Dataframe(
                    value=self.trader.get_holdings_df(),
                    label="Holdings",
                    headers=["Symbol", "Quantity"],
                    row_count=(5, "dynamic"),
                    col_count=2,
                    max_height=200,
                    elem_classes=["dataframe-fix-small"],
                )
                self.transactions_table = gr.Dataframe(
                    value=self.trader.get_transactions_df(),
                    label="Recent Transactions",
                    headers=["Timestamp", "Symbol", "Quantity", "Price", "Rationale"],
                    row_count=(5, "dynamic"),
                    col_count=5,
                    max_height=200,
                    elem_classes=["dataframe-fix"],
                )

        # Refresh UI cards periodically (slower for heavy data)
        timer = gr.Timer(value=120)
        timer.tick(
            fn=self.refresh,
            inputs=[],
            outputs=[
                self.portfolio_value,
                self.chart,
                self.holdings_table,
                self.transactions_table,
            ],
            show_progress="hidden",
            queue=False,
        )

        # Fast log refresher
        log_timer = gr.Timer(value=0.5)
        log_timer.tick(
            fn=self.trader.get_logs,
            inputs=[self.log],
            outputs=[self.log],
            show_progress="hidden",
            queue=False,
        )

    def refresh(self):
        # Always reload data from backend for fresh values
        self.trader.reload()
        return (
            self.trader.get_portfolio_value(),
            self.trader.get_portfolio_value_chart(),
            self.trader.get_holdings_df(),
            self.trader.get_transactions_df(),
        )


# -------------------------------------------------------------------
class TradingController:
    """Runs the agent trading loop in the background."""

    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.stop_event: Optional[asyncio.Event] = None
        self.running: bool = False

    async def start(self, interval_minutes: int, run_when_closed: bool):
        if self.task and not self.task.done():
            return "⚠️ Trading is already running."

        self.stop_event = asyncio.Event()
        add_trace_processor(LogTracer())
        traders = create_traders()

        async def _loop():
            try:
                while not self.stop_event.is_set():
                    if run_when_closed or is_market_open():
                        await asyncio.gather(*[t.run() for t in traders])
                    try:
                        await asyncio.wait_for(
                            self.stop_event.wait(), timeout=interval_minutes * 60
                        )
                    except asyncio.TimeoutError:
                        continue
            except asyncio.CancelledError:
                pass

        self.task = asyncio.create_task(_loop())
        self.running = True
        return f"✅ Trading started (interval: {interval_minutes} min; run_when_closed={run_when_closed})."

    async def stop(self):
        if not self.task or self.task.done():
            self.running = False
            return "ℹ️ Trading is not running."
        if self.stop_event:
            self.stop_event.set()
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None
        self.stop_event = None
        self.running = False
        return "🛑 Trading stopped."


# -------------------------------------------------------------------
def create_ui():
    """Create the main Gradio UI for the trading simulation"""
    traders = [
        Trader(trader_name, lastname, model_name)
        for trader_name, lastname, model_name in zip(names, lastnames, short_model_names)
    ]
    trader_views = [TraderView(trader) for trader in traders]

    controller = TradingController()

    with gr.Blocks(
        title="Traders",
        css=css
        + """
        .card { border: 1px solid #ccc; border-radius: 8px; padding: 5px; background-color: #f9f9f9; }
        """,
        js=js,
        theme=gr.themes.Default(primary_hue="sky"),
        fill_width=True,
    ) as ui:
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Trading Session Controls")
                interval = gr.Number(value=60, label="Interval (minutes)", precision=0)
                run_when_closed = gr.Checkbox(value=False, label="Run when market is closed")
                start_btn = gr.Button("Start Trading", variant="primary")
                stop_btn = gr.Button("Stop Trading", variant="stop")
                status = gr.HTML("<em>Idle</em>")

                async def _start(i, r):
                    try:
                        i = int(i) if i is not None else 60
                    except Exception:
                        i = 60
                    msg = await controller.start(i, bool(r))
                    start_state = gr.update(interactive=not controller.running)
                    stop_state = gr.update(interactive=controller.running)
                    return msg, start_state, stop_state

                async def _stop():
                    msg = await controller.stop()
                    start_state = gr.update(interactive=True)
                    stop_state = gr.update(interactive=False)
                    return msg, start_state, stop_state

                start_btn.click(
                    _start,
                    inputs=[interval, run_when_closed],
                    outputs=[status, start_btn, stop_btn],
                )
                stop_btn.click(_stop, inputs=None, outputs=[status, start_btn, stop_btn])

                start_btn.interactive = True
                stop_btn.interactive = False

            # Four trader cards in one row
            with gr.Column(scale=4):
                with gr.Row(equal_height=True):
                    for tv in trader_views:
                        with gr.Column(scale=1):
                            tv.make_ui()

    return ui


if __name__ == "__main__":
    ui = create_ui()
    ui.launch(inbrowser=True)
