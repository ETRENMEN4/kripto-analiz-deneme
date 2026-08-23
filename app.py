import pandas as pd
import requests
import streamlit as st

# Streamlit Arayüz Ayarları
st.set_page_config(page_title="BtcTurk AI & AquiverAI Bot", layout="wide")
st.title("📈 BtcTurk Canlı Analiz & AquiverAI Trading Botu")


# BtcTurk API Veri Çekme
@st.cache_data(ttl=15)
def get_all_pairs_analysis():
    try:
        ticker_url = "https://api.btcturk.com/api/v2/ticker"
        res = requests.get(ticker_url, timeout=10).json()
        data = res.get("data", [])

        analyzed_list = []

        for item in data:
            symbol = item["pair"]
            if symbol.endswith("USDT") or symbol.endswith("TRY"):
                last_price = float(item["last"])
                high = float(item["high"])
                low = float(item["low"])

                volatility = ((high - low) / low) * 100 if low > 0 else 5.0
                ai_profit_margin = round(
                    max(2.5, min(volatility / 2, 100.0)), 1
                )
                ai_stop_margin = round(max(1.5, ai_profit_margin / 2), 1)

                is_bullish = last_price > (high + low) / 2
                potential_score = (
                    ai_profit_margin if is_bullish else -ai_stop_margin
                )

                analyzed_list.append(
                    {
                        "pair": symbol,
                        "last": last_price,
                        "high": high,
                        "low": low,
                        "profit_margin": ai_profit_margin,
                        "stop_margin": ai_stop_margin,
                        "is_bullish": is_bullish,
                        "score": potential_score,
                        "currency": "₺" if symbol.endswith("TRY") else "$",
                    }
                )

        df = pd.DataFrame(analyzed_list)
        if not df.empty:
            df = df.sort_values(by="score", ascending=False)
        return df
    except Exception as e:
        st.error(f"Veri çekilirken hata oluştu: ({e})")
        return pd.DataFrame()


df_analysis = get_all_pairs_analysis()

# --- AQUIVER AI HAFIZA YÖNETİMİ ---
if "bot_balance" not in st.session_state:
    st.session_state.bot_balance = 10000.0
if "bot_positions" not in st.session_state:
    st.session_state.bot_positions = {}
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

if not df_analysis.empty:
    pairs_list = df_analysis["pair"].tolist()

    if "selected_coin" not in st.session_state:
        st.session_state.selected_coin = pairs_list[0]

    # --- SOL MENÜ ---
    st.sidebar.subheader("📌 Coin Seçimi")
    selected_from_select = st.sidebar.selectbox(
        "Analiz Edilecek Coin:",
        pairs_list,
        index=pairs_list.index(st.session_state.selected_coin)
        if st.session_state.selected_coin in pairs_list
        else 0,
    )

    if selected_from_select != st.session_state.selected_coin:
        st.session_state.selected_coin = selected_from_select
        st.rerun()

    # Kasa Sırfırlama Seçeneği
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Kasayı $10,000'a Sıfırla"):
        st.session_state.bot_balance = 10000.0
        st.session_state.bot_positions = {}
        st.session_state.trade_history = []
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔥 AI Potansiyel Sıralaması")
    for _, row in df_analysis.iterrows():
        symbol_name = row["pair"]
        label = (
            f"🟢 {symbol_name}: +{row['profit_margin']}%"
            if row["is_bullish"]
            else f"🔴 {symbol_name}: -{row['stop_margin']}%"
        )
        if st.sidebar.button(label, key=f"btn_{symbol_name}"):
            st.session_state.selected_coin = symbol_name
            st.rerun()

    # 🤖 AQUIVER AI GENEL TARAMA & OTO-TRADING MOTORU
    # 1. Mevcut Açık Pozisyonların Kâr/Zarar Kontrolü
    for pos_coin, pos_data in list(st.session_state.bot_positions.items()):
        coin_match = df_analysis[df_analysis["pair"] == pos_coin]
        if not coin_match.empty:
            curr_price = coin_match.iloc[0]["last"]
            curr_currency = coin_match.iloc[0]["currency"]
            p_margin = coin_match.iloc[0]["profit_margin"]
            s_margin = coin_match.iloc[0]["stop_margin"]

            entry_p = pos_data["entry_price"]
            pnl_pct = ((curr_price - entry_p) / entry_p) * 100
            current_val = pos_data["amount"] * curr_price
            pnl_amount = current_val - pos_data["cost"]

            # Satış Koşulu
            if pnl_pct >= p_margin or pnl_pct <= -s_margin:
                st.session_state.bot_balance += current_val
                status_text = (
                    "KÂR İLE KAPATILDI"
                    if pnl_amount > 0
                    else "ZARAR KES (STOP) YAPILDI"
                )
                pnl_sign = "+" if pnl_amount > 0 else ""

                st.session_state.trade_history.append(
                    {
                        "Coin": pos_coin,
                        "Tür": "SATIŞ",
                        "Fiyat": f"{curr_currency}{curr_price:,.2f}",
                        "Net Kâr/Zarar": f"{pnl_sign}${pnl_amount:,.2f}",
                        "Durum": status_text,
                    }
                )
                del st.session_state.bot_positions[pos_coin]

    # 2. Çeşitlendirilmiş Yeni Pozisyon Açma (Farklı Coinler İçin Tarama)
    bullish_candidates = df_analysis[
        (df_analysis["is_bullish"] == True)
        & (~df_analysis["pair"].isin(st.session_state.bot_positions.keys()))
    ]

    if not bullish_candidates.empty and st.session_state.bot_balance >= 1000:
        # En uygun ilk yeni coine pozisyon açar
        target_buy_coin = bullish_candidates.iloc[0]
        buy_symbol = target_buy_coin["pair"]
        buy_price = target_buy_coin["last"]
        buy_currency = target_buy_coin["currency"]

        buy_amount_usd = 1000.0
        coin_qty = buy_amount_usd / buy_price
        st.session_state.bot_balance -= buy_amount_usd

        st.session_state.bot_positions[buy_symbol] = {
            "entry_price": buy_price,
            "amount": coin_qty,
            "cost": buy_amount_usd,
        }
        st.session_state.trade_history.append(
            {
                "Coin": buy_symbol,
                "Tür": "ALIM",
                "Fiyat": f"{buy_currency}{buy_price:,.2f}",
                "Net Kâr/Zarar": "$0.00",
                "Durum": "AquiverAI Pozisyon Açtı",
            }
        )

    # --- ANA EKRAN ---
    selected_pair = st.session_state.selected_coin
    coin_data = df_analysis[df_analysis["pair"] == selected_pair].iloc[0]

    price = coin_data["last"]
    high = coin_data["high"]
    low = coin_data["low"]
    currency = coin_data["currency"]

    # Portföy Göstergeleri
    st.markdown("---")
    st.subheader("🤖 AquiverAI Sanal Trading Portföyü")
    b1, b2, b3 = st.columns(3)
    b1.metric("Kasadaki Sanal Bakiye", f"${st.session_state.bot_balance:,.2f}")
    b2.metric("Aktif Açık Pozisyon Sayısı", len(st.session_state.bot_positions))
    b3.metric("Toplam Tamamlanan İşlem", len(st.session_state.trade_history))

    if selected_pair in st.session_state.bot_positions:
        pos = st.session_state.bot_positions[selected_pair]
        current_val = pos["amount"] * price
        pnl_val = current_val - pos["cost"]
        pnl_sign = "+" if pnl_val > 0 else ""

        st.info(
            f"⚡ **AquiverAI Şu An {selected_pair} Pozisyonunda!** | Alış Fiyatı: {currency}{pos['entry_price']:,.2f} | Anlık Durum: **{pnl_sign}${pnl_val:,.2f}**"
        )

    st.markdown("---")

    # Bilgi Kartları
    col1, col2, col3 = st.columns(3)
    col1.metric("Son Fiyat", f"{currency}{price:,.2f}")
    col2.metric("24s En Yüksek", f"{currency}{high:,.2f}")
    col3.metric("24s En Düşük", f"{currency}{low:,.2f}")

    # TradingView Grafiği
    st.subheader("💡 Canlı Mum Grafiği")
    base_symbol = selected_pair.replace("TRY", "").replace("USDT", "")
    custom_symbols = {"BILL": "BYBIT:BILLUSDT"}
    tv_symbol = (
        custom_symbols[base_symbol]
        if base_symbol in custom_symbols
        else f"BINANCE:{base_symbol}USDT"
    )

    tradingview_html = f"""
    <div class="tradingview-widget-container">
      <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_1&symbol={tv_symbol}&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=dark&style=1&timezone=Etc%2FUTC" width="100%" height="500" frameborder="0" allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(tradingview_html, height=520)

    # Bot İşlem Geçmişi Tablosu
    if st.session_state.trade_history:
        st.subheader("📜 AquiverAI İşlem Geçmişi")
        st.dataframe(
            pd.DataFrame(st.session_state.trade_history).iloc[::-1],
            use_container_width=True,
        )
