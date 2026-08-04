from datetime import datetime,timezone
from .view_models import build_daily_decision_view
def render_app(api_client,session_token:str):
 import streamlit as st
 payload=api_client.get_daily_decisions(session_token,datetime.now(timezone.utc));view=build_daily_decision_view(payload);st.title("Quant Trading Daily Decisions");st.caption(f"Mode: {view.mode} | as_of: {view.as_of.isoformat()}")
 if view.hard_block:
  st.error("Trading actions blocked: "+"; ".join(view.blocking_reasons))
 left,right=st.columns(2)
 with left:st.subheader("ETF timing");st.json(dict(view.etf))
 with right:st.subheader("Equity daily selection");st.json(dict(view.equity))
 st.subheader("Combined net recommendations")
 for recommendation in view.recommendations:st.write({"instrument_id":str(recommendation.instrument_id),"side":recommendation.side,"quantity":recommendation.quantity,"source":"COMBINED_NET"})
 return view

