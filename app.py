import sqlite3
import pandas as pd
import requests
import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler

# Streamlit Arayüz Ayarları
st.set_page_config(
    page_title="BtcTurk AI & AquiverAI 7/24 Bot", layout="wide"
)
st.title("📈 BtcTurk Canlı Analiz & 7/24 Otomatik AquiverAI Botu")

# --- VERİTABANI KURULUMU VE YÖNETİMİ ---
DB_FILE = "aquiver_bot.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Kasa Bakiyesi Tablosu
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS balance (id INTEGER PRIMARY KEY, amount REAL)"
    )
    cursor.execute("SELECT COUNT(*) FROM balance")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO balance (id, amount) VALUES (1, 10000.0)")

    # Açık Pozisyonlar Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            pair TEXT PRIMARY KEY,
            entry_price REAL,
            amount REAL,
            cost REAL
        )
    """)

    # İşlem Geçmişi Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            type TEXT,
            price TEXT,
            pnl TEXT,
            status TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_db_data():
    conn = sqlite3.connect(DB_FILE)
    balance = conn.cursor().execute("SELECT amount FROM balance").fetchone()[0]
    positions_df = pd.read_sql_query("SELECT * FROM positions", conn)
    history_df = pd.read_sql_query(
        "SELECT pair as Coin, type as Tür, price as Fiyat, pnl as 'Net Kâr/Zarar', status as Durum, timestamp as Tarih FROM history ORDER BY id DESC",
        conn,
    )
    conn.close()

    positions_dict = {}
    for _, row in positions_df.iterrows():
        positions_dict[row["pair"]] = {
            "entry_price": row["entry_price"],
            "amount": row["amount"],
            "cost": row["cost"],
        }

    return balance, positions_dict, history_df


def reset_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE balance SET amount = 10000.0 WHERE id = 1")
    cursor.execute("DELETE FROM positions")
    cursor.execute("DELETE FROM history")
    conn.commit()
    conn.close()


# API Veri Analiz Fonksiyonu
def fetch_btcturk_analysis():
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
    except Exception:
        return pd.DataFrame()


# --- 7/24 ARKA PLAN OTO-TRADING MOTORU ---
def run_aquiver_bot_cycle():
    df_analysis = fetch_btcturk_analysis()
    if df_analysis.empty:
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    balance = cursor.execute("SELECT amount FROM balance").fetchone()[0]
    positions_df = pd.read_sql_query("SELECT * FROM positions", conn)

    positions = {}
    for _, row in positions_df.iterrows():
        positions[row["pair"]] = {
            "entry_price": row["entry_price"],
            "amount": row["amount"],
            "cost": row["cost"],
        }

    # 1. Açık Pozisyonların Takibi ve Kapatılması
    for pos_coin, pos_data in list(positions.items()):
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

            if pnl_pct >= p_margin or pnl_pct <= -s_margin:
                new_balance = balance + current_val
                cursor.execute(
                    "UPDATE balance SET amount = ? WHERE id = 1",
                    (new_balance,),
                )
                cursor.execute(
                    "DELETE FROM positions WHERE pair = ?", (pos_coin,)
                )

                status_text = (
                    "KÂR İLE KAPATILDI"
                    if pnl_amount > 0
                    else "ZARAR KES (STOP) YAPILDI"
                )
                pnl_sign = "+" if pnl_amount > 0 else ""
                cursor.execute(
                    "INSERT INTO history (pair, type, price, pnl, status) VALUES (?, ?, ?, ?, ?)",
                    (
                        pos_coin,
                        "SATIŞ",
                        f"{curr_currency}{curr_price:,.2f}",
                        f"{pnl_sign}${pnl_amount:,.2f}",
                        status_text,
                    ),
                )
                balance = new_balance

    # 2. Yeni Çeşitlendirilmiş Pozisyon Açma
    bullish_candidates = df_analysis[
        (df_analysis["is_bullish"] == True)
        & (~df_analysis["pair"].isin(positions.keys()))
    ]

    if not bullish_candidates.empty and balance >= 1000:
        target_buy_coin = bullish_candidates.iloc[0]
        buy_symbol = target_buy_coin["pair"]
        buy_price = target_buy_coin["last"]
        buy_currency = target_buy_coin["currency"]

        buy_amount_usd = 1000.0
        coin_qty = buy_amount_usd / buy_price
        new_balance = balance - buy_amount_usd

        cursor.execute(
            "UPDATE balance SET amount = ? WHERE id = 1", (new_balance,)
        )
        cursor.execute(
            "INSERT INTO positions (pair, entry_price, amount, cost) VALUES (?, ?, ?, ?)",
            (buy_symbol, buy_price, coin_qty, buy_amount_usd),
        )
        cursor.execute(
            "INSERT INTO history (pair, type, price, pnl, status) VALUES (?, ?, ?, ?, ?)",
            (
                buy_symbol,
                "ALIM",
                f"{buy_currency}{buy_price:,.2f}",
                "$0.00",
                "AquiverAI Pozisyon Açtı",
            ),
        )

    conn.commit()
    conn.close()


# ARKA PLAN ZAMANLAYICISINI BAŞLATMA (HER 30 SANİYEDE BİR ÇALIŞIR)
@st.cache_resource
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_aquiver_bot_cycle, "interval", seconds=30)
    scheduler.start()
    return scheduler


start_scheduler()

# --- ARAYÜZ VE GÖSTERGELER ---
df_analysis = fetch_btcturk_analysis()
balance, bot_positions, trade_history_df = get_db_data()

if not df_analysis.empty:
    pairs_list = df_analysis["pair"].tolist()
    if "selected_coin" not in st.session_state:
        st.session_state.selected_coin = pairs_list[0]

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
    if st.sidebar.button("🔄 Kasayı $10,000'a Sıfırla"):
        reset_db()
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

    selected_pair = st.session_state.selected_coin
    coin_data = df_analysis[df_analysis["pair"] == selected_pair].iloc[0]
    price, high, low, currency = (
        coin_data["last"],
        coin_data["high"],
        coin_data["low"],
        coin_data["currency"],
    )

    st.markdown("---")
    st.subheader("🤖 AquiverAI Sanal Trading Portföyü (7/24 Canlı)")
    b1, b2, b3 = st.columns(3)
    b1.metric("Kasadaki Sanal Bakiye", f"${balance:,.2f}")
    b2.metric("Aktif Açık Pozisyon Sayısı", len(bot_positions))
    b3.metric("Toplam İşlem Kaydı", len(trade_history_df))

    if selected_pair in bot_positions:
        pos = bot_positions[selected_pair]
        current_val = pos["amount"] * price
        pnl_val = current_val - pos["cost"]
        pnl_sign = "+" if pnl_val > 0 else ""
        st.info(
            f"⚡ **AquiverAI Şu An {selected_pair} Pozisyonunda!** | Alış Fiyatı: {currency}{pos['entry_price']:,.2f} | Anlık Durum: **{pnl_sign}${pnl_val:,.2f}**"
        )

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    col1.metric("Son Fiyat", f"{currency}{price:,.2f}")
    col2.metric("24s En Yüksek", f"{currency}{high:,.2f}")
    col3.metric("24s En Düşük", f"{currency}{low:,.2f}")

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

    if not trade_history_df.empty:
        st.subheader("📜 AquiverAI 7/24 İşlem Geçmişi")
        st.dataframe(trade_history_df, use_container_width=True)
