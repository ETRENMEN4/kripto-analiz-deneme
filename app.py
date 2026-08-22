import pandas as pd
import requests
import streamlit as st

# Streamlit Arayüz Ayarları
st.set_page_config(page_title="BtcTurk AI Sinyal Paneli", layout="wide")
st.title("📈 BtcTurk Canlı Kripto Analiz & Otomatik AI Tahmin Paneli")


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

                # Volatilite ve AI Potansiyel Oranı
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

if not df_analysis.empty:
    pairs_list = df_analysis["pair"].tolist()

    # Session State (Seçili Coini Hafızada Tutma)
    if "selected_coin" not in st.session_state:
        st.session_state.selected_coin = pairs_list[0]

    # --- SOL MENÜ ---
    st.sidebar.subheader("📌 Coin Seçimi")

    selected_from_select = st.sidebar.selectbox(
        "Analiz Edilecek Coini Seçin:",
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
    st.sidebar.caption("Tıklayarak grafiğini açabilirsiniz:")

    for _, row in df_analysis.iterrows():
        symbol_name = row["pair"]
        if row["is_bullish"]:
            label = f"🟢 {symbol_name}: +%{row['profit_margin']}"
        else:
            label = f"🔴 {symbol_name}: -%{row['stop_margin']}"

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

    # Bilgi Kartları
    col1, col2, col3 = st.columns(3)
    col1.metric("Son Fiyat", f"{currency}{price:,.2f}")
    col2.metric("24s En Yüksek", f"{currency}{high:,.2f}")
    col3.metric("24s En Düşük", f"{currency}{low:,.2f}")

    st.markdown("---")
    st.subheader(f"🤖 {selected_pair} Otomatik AI Analiz & Hedef")

    if is_bullish:
        st.success(
            f"**Durum:** 🚀 YÜKSELİŞ POTANSİYELİ YÜKSEK (AI Tahmini Yükseliş: +%{ai_profit_margin})"
        )
    else:
        st.error(
            f"**Durum:** 🔻 DÜŞÜŞ POTANSİYELİ YÜKSEK (AI Tahmini Risk: -%{ai_stop_margin})"
        )

    # Tahmini Hedef Seviyeleri
    h1, h2 = st.columns(2)
    h1.info(
        f"🎯 **AI Otomatik Yükseliş Hedefi (+%{ai_profit_margin}):** {currency}{target_price:,.2f}"
    )
    h2.warning(
        f"🛡️ **AI Otomatik Destek / Stop Seviyesi (-%{ai_stop_margin}):** {currency}{stop_price:,.2f}"
    )

    # TradingView Canlı Mum Grafiği
    st.subheader("💡 Canlı Mum Grafiği")

    base_symbol = selected_pair.replace("TRY", "").replace("USDT", "")

    # Özel Sembol Kuralları (Borsa Kısıtlamasını Kaldıran Mantık)
    custom_symbols = {
        "BILL": "BYBIT:BILLUSDT",  # TradingView'da Bybit borsası üzerinden direkt açar
    }

    if base_symbol in custom_symbols:
        tv_symbol = custom_symbols[base_symbol]
    else:
        # Genel arama için standart kalıp
        tv_symbol = f"BINANCE:{base_symbol}USDT"

    tradingview_html = f"""
    <div class="tradingview-widget-container">
      <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_1&symbol={tv_symbol}&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=dark&style=1&timezone=Etc%2FUTC" width="100%" height="500" frameborder="0" allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(tradingview_html, height=520)
else:
    st.warning("BtcTurk verileri şu an çekilemiyor.")