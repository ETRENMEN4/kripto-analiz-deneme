import pandas as pd
import requests
import streamlit as st

# Streamlit Arayüz Ayarları
st.set_page_config(page_title="BtcTurk AI & AquiverAI Bot", layout="wide")
st.title("📈 BtcTurk Canlı Analiz & AquiverAI Trading Botu")


# BtcTurk API'den Tüm Verileri Çekme ve AI Analizi Yapma
@st.cache_data(ttl=30)
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

# --- AQUIVER AI SİMÜLASYON HAFIZASI ---
if "bot_balance" not in st.session_state:
    st.session_state.bot_balance = 10000.0  # $10,000 Başlangıç Sanal Bakiyesi
if "bot_positions" not in st.session_state:
    st.session_state.bot_positions = {}  # Açık pozisyonlar
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []  # İşlem geçmişi

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

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔥 AI Potansiyel Sıralaması")
    for _, row in df_analysis.iterrows():
        symbol_name = row["pair"]
        label = (
            f"🟢 {symbol_name}: +%{row['profit_margin']}"
            if row["is_bullish"]
            else f"🔴 {symbol_name}: -%{row['stop_margin']}"
        )
        if st.sidebar.button(label, key=f"btn_{symbol_name}"):
            st.session_state.selected_coin = symbol_name
            st.rerun()

    # --- ANA EKRAN ---
    selected_pair = st.session_state.selected_coin
    coin_data = df_analysis[df_analysis["pair"] == selected_pair].iloc[0]

    price = coin_data["last"]
    high = coin_data["high"]
    low = coin_data["low"]
    currency = coin_data["currency"]
    ai_profit_margin = coin_data["profit_margin"]
    ai_stop_margin = coin_data["stop_margin"]
    is_bullish = coin_data["is_bullish"]

    target_price = price * (1 + ai_profit_margin / 100)
    stop_price = price * (1 - ai_stop_margin / 100)

    # 🤖 AQUIVER AI OTO-TRADING MOTORU (HER YENİLEMEDE KONTROL EDER)
    # 1. Açık Pozisyon Kâr/Zarar Kontrolü
    if selected_pair in st.session_state.bot_positions:
        pos = st.session_state.bot_positions[selected_pair]
        entry_p = pos["entry_price"]
        pnl_pct = ((price - entry_p) / entry_p) * 100

        # Kâr Al (Take Profit) veya Erken Stop-Loss
        if pnl_pct >= ai_profit_margin or pnl_pct <= -ai_stop_margin:
            sold_amount = pos["amount"] * price
            st.session_state.bot_balance += sold_amount
            status_text = "KÂR İLE KAPATILDI" if pnl_pct > 0 else "ZARAR KES (STOP) YAPILDI"
            st.session_state.trade_history.append(
                {
                    "Coin": selected_pair,
                    "Tür": "SATIŞ",
                    "Fiyat": f"{currency}{price:,.2f}",
                    "Kâr/Zarar": f"%{pnl_pct:.2f}",
                    "Durum": status_text,
                }
            )
            del st.session_state.bot_positions[selected_pair]

    # 2. Yeni Pozisyon Açma Kontrolü (Güçlü Yükseliş Sinyali Varsa ve Bakiye Yeterliyse)
    elif is_bullish and st.session_state.bot_balance >= 1000:
        buy_amount_usd = 1000.0  # Her işleme $1000 ayırır
        coin_qty = buy_amount_usd / price
        st.session_state.bot_balance -= buy_amount_usd

        st.session_state.bot_positions[selected_pair] = {
            "entry_price": price,
            "amount": coin_qty,
            "cost": buy_amount_usd,
        }
        st.session_state.trade_history.append(
            {
                "Coin": selected_pair,
                "Tür": "ALIM",
                "Fiyat": f"{currency}{price:,.2f}",
                "Kâr/Zarar": "%0.00",
                "Durum": "AquiverAI Pozisyon Açtı",
            }
        )

    # --- AQUIVER AI CANLI PANELİ ---
    st.markdown("---")
    st.subheader("🤖 AquiverAI Sanal Trading Portföyü")
    b1, b2, b3 = st.columns(3)
    b1.metric("Kasadaki Sanal Bakiye", f"${st.session_state.bot_balance:,.2f}")
    b2.metric("Aktif Açık Pozisyon Sayısı", len(st.session_state.bot_positions))
    b3.metric("Toplam Tamamlanan İşlem", len(st.session_state.trade_history))

    if selected_pair in st.session_state.bot_positions:
        pos = st.session_state.bot_positions[selected_pair]
        pnl = ((price - pos["entry_price"]) / pos["entry_price"]) * 100
        st.info(
            f"⚡ **AquiverAI Şu An {selected_pair} Pozisyonunda!** | Alış Fiyatı: {currency}{pos['entry_price']:,.2f} | Anlık Durum: **%{pnl:.2f}**"
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
