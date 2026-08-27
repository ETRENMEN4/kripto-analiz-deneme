import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
import pandas as pd
import requests
import streamlit as st

# Streamlit Arayüz Ayarları
st.set_page_config(
    page_title="BtcTurk AI & AquiverAI 7/24 Bot", layout="wide"
)

st.title("📈 BtcTurk Canlı Analiz & 7/24 Otomatik AquiverAI Botu")

# --- VERİTABANI KURULUMU VE YÖNETİMİ ---
DB_FILE = "aquiver_bot_try.db"

# 1. YEREL TSİ SAAT DİLİMİ (UTC+3 FIX)
def get_turkey_time():
    """Zaman damgalarını UTC+3 Türkiye saati olarak hesaplar ve döndürür."""
    utc_now = datetime.now(timezone.utc)
    turkey_now = utc_now + timedelta(hours=3)
    return turkey_now.strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS balance (id INTEGER PRIMARY KEY, amount REAL)"
    )
    cursor.execute("SELECT COUNT(*) FROM balance")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO balance (id, amount) VALUES (1, 100000.0)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            min_buy_amount REAL,
            max_buy_amount REAL
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO settings (id, min_buy_amount, max_buy_amount) VALUES (1, 100.0, 100000.0)"
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            pair TEXT PRIMARY KEY,
            entry_price REAL,
            highest_price REAL,
            amount REAL,
            cost REAL,
            bought_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            type TEXT,
            price TEXT,
            pnl TEXT,
            status TEXT,
            timestamp TEXT
        )
    """)

    cursor.execute("DELETE FROM positions WHERE cost <= 0 OR amount <= 0")
    conn.commit()
    conn.close()


init_db()


def get_db_data():
    conn = sqlite3.connect(DB_FILE)
    balance = conn.cursor().execute("SELECT amount FROM balance").fetchone()[0]

    try:
        settings_row = (
            conn.cursor()
            .execute(
                "SELECT min_buy_amount, max_buy_amount FROM settings WHERE id = 1"
            )
            .fetchone()
        )
        min_buy = float(settings_row[0]) if settings_row and settings_row[0] is not None else 100.0
        max_buy = float(settings_row[1]) if settings_row and settings_row[1] is not None else 100000.0
    except sqlite3.OperationalError:
        min_buy, max_buy = 100.0, 100000.0

    positions_df = pd.read_sql_query(
        "SELECT * FROM positions WHERE cost > 0 AND amount > 0", conn
    )
    history_df = pd.read_sql_query(
        "SELECT pair as Coin, type as Tür, price as Fiyat, pnl as 'Net Kâr/Zarar', status as Durum, timestamp as Tarih FROM history ORDER BY id DESC",
        conn,
    )
    conn.close()

    positions_dict = {}
    for _, row in positions_df.iterrows():
        entry_p = float(row["entry_price"])
        h_price = row.get("highest_price")
        highest_p = float(h_price) if (h_price is not None and not pd.isna(h_price)) else entry_p

        positions_dict[row["pair"]] = {
            "entry_price": entry_p,
            "highest_price": highest_p,
            "amount": float(row["amount"]),
            "cost": float(row["cost"]),
            "bought_at": row.get("bought_at", "—"),
        }

    return float(balance), positions_dict, history_df, min_buy, max_buy


def reset_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE balance SET amount = 100000.0 WHERE id = 1")
    cursor.execute("DELETE FROM positions")
    cursor.execute("DELETE FROM history")
    conn.commit()
    conn.close()


# --- PİYASA DUYGU DURUMU (FEAR & GREED INDEX) ---
def fetch_fear_and_greed_index():
    """Kripto piyasası Korku ve Açgözlülük İndeksini çeker."""
    try:
        url = "https://api.alternative.me/fng/"
        res = requests.get(url, timeout=5).json()
        val = int(res["data"][0]["value"])
        text = res["data"][0]["value_classification"]
        return val, text
    except Exception:
        return 50, "Neutral"  # Bağlantı hatasında nötr kabul et


def fetch_btcturk_analysis():
    try:
        ticker_url = "https://api.btcturk.com/api/v2/ticker"
        res = requests.get(ticker_url, timeout=10).json()
        data = res.get("data", [])

        analyzed_list = []
        for item in data:
            symbol = str(item.get("pair", ""))
            if symbol.endswith("TRY"):
                last_price = float(item.get("last", 0))
                high = float(item.get("high", 0))
                low = float(item.get("low", 0))

                if last_price <= 0:
                    continue

                volatility = ((high - low) / low) * 100 if low > 0 else 5.0
                ai_profit_margin = round(max(5.0, min(volatility / 2, 100.0)), 1)
                ai_stop_margin = round(max(2.5, ai_profit_margin / 2), 1)

                mid_price = (high + low) / 2 if (high > 0 and low > 0) else 0
                is_bullish = last_price >= mid_price if mid_price > 0 else True
                potential_score = ai_profit_margin if is_bullish else -ai_stop_margin

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
                        "currency": "₺",
                    }
                )

        df = pd.DataFrame(analyzed_list)
        if not df.empty:
            df = df.sort_values(by="score", ascending=False)
        return df
    except Exception:
        return pd.DataFrame()


def is_market_safe(cursor, is_btc_bullish, fng_value):
    """
    İki Aşamalı Güvenlik: 
    1. BTC Trend Kontrolü 
    2. Piyasa Psikolojisi (20 < F&G < 80)
    """
    if not is_btc_bullish:
        return False

    # Extreme Greed (> 80) veya Extreme Fear (< 20) durumunda yeni alımları kilitle
    if fng_value > 80 or fng_value < 20:
        return False

    utc_now = datetime.now(timezone.utc)
    one_hour_ago = (utc_now + timedelta(hours=3) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute(
        "SELECT COUNT(*) FROM history WHERE type='SATIŞ' AND status LIKE '%STOP%' AND timestamp >= ?",
        (one_hour_ago,),
    )
    recent_stops = cursor.fetchone()[0]

    if recent_stops >= 2:
        return False

    return True


def run_aquiver_bot_cycle():
    """Bot mantık döngüsü"""
    df_analysis = fetch_btcturk_analysis()
    if df_analysis.empty:
        return

    fng_val, fng_text = fetch_fear_and_greed_index()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM positions WHERE cost <= 0 OR amount <= 0")
    conn.commit()

    balance = float(cursor.execute("SELECT amount FROM balance").fetchone()[0])

    try:
        settings_row = cursor.execute(
            "SELECT min_buy_amount, max_buy_amount FROM settings WHERE id = 1"
        ).fetchone()
        min_buy_setting = float(settings_row[0]) if settings_row and settings_row[0] is not None else 100.0
        max_buy_setting = float(settings_row[1]) if settings_row and settings_row[1] is not None else 100000.0
    except Exception:
        min_buy_setting, max_buy_setting = 100.0, 100000.0

    positions_df = pd.read_sql_query(
        "SELECT * FROM positions WHERE cost > 0 AND amount > 0", conn
    )

    positions = {}
    for _, row in positions_df.iterrows():
        p_coin = row["pair"]
        entry_p = float(row["entry_price"])
        h_price = row.get("highest_price")
        highest_p = float(h_price) if (h_price is not None and not pd.isna(h_price)) else entry_p

        positions[p_coin] = {
            "entry_price": entry_p,
            "highest_price": highest_p,
            "amount": float(row["amount"]),
            "cost": float(row["cost"]),
        }

    btc_match = df_analysis[df_analysis["pair"] == "BTCTRY"]
    is_btc_bullish = btc_match.iloc[0]["is_bullish"] if not btc_match.empty else True

    # --- AÇIK POZİSYONLARIN TAKİBİ & ZARAR KORUMASI ---
    for pos_coin, pos_data in list(positions.items()):
        coin_match = df_analysis[df_analysis["pair"] == pos_coin]
        if not coin_match.empty:
            curr_price = float(coin_match.iloc[0]["last"])
            p_margin = float(coin_match.iloc[0]["profit_margin"])
            s_margin = float(coin_match.iloc[0]["stop_margin"])

            entry_p = pos_data["entry_price"]
            highest_p = max(pos_data["highest_price"], curr_price)

            cursor.execute(
                "UPDATE positions SET highest_price = ? WHERE pair = ?",
                (highest_p, pos_coin),
            )

            pnl_pct = ((curr_price - entry_p) / entry_p) * 100
            current_val = pos_data["amount"] * curr_price
            pnl_amount = current_val - pos_data["cost"]

            trailing_stop_price = highest_p * (1 - (s_margin / 100))

            # ZARAR KORUMASI ŞARTLARI:
            # 1. Normal Hedef Kâr (% Margin)
            # 2. İz Süren Stop (Trailing Stop)
            # 3. BTC Trendinin Bozulması veya Piyasa "Aşırı Korku" (<20) Halinde Zarardaki Pozisyonu Kapatma
            is_in_loss = pnl_amount < 0
            emergency_exit = is_in_loss and (not is_btc_bullish or fng_val < 20)

            if pnl_pct >= p_margin or curr_price <= trailing_stop_price or emergency_exit:
                new_balance = balance + current_val
                cursor.execute(
                    "UPDATE balance SET amount = ? WHERE id = 1",
                    (new_balance,),
                )
                cursor.execute(
                    "DELETE FROM positions WHERE pair = ?", (pos_coin,)
                )

                if emergency_exit:
                    reason = "BTC TREND BOZULDU" if not is_btc_bullish else "AŞIRI KORKU ALARMI"
                    status_text = f"ACİL KORUMA STOPU ({reason})"
                elif pnl_amount > 0:
                    status_text = "KÂR İLE KAPATILDI"
                else:
                    status_text = "İZ SÜREN STOP YAPILDI"

                pnl_sign = "+" if pnl_amount > 0 else ""
                cursor.execute(
                    "INSERT INTO history (pair, type, price, pnl, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        pos_coin,
                        "SATIŞ",
                        f"₺{curr_price:,.2f}",
                        f"{pnl_sign}₺{pnl_amount:,.2f}",
                        status_text,
                        get_turkey_time(),
                    ),
                )
                balance = new_balance

    # --- YENİ ALIM MANTIĞI (İki Aşamalı Güvenlik) ---
    if is_market_safe(cursor, is_btc_bullish, fng_val):
        bullish_candidates = df_analysis[
            (df_analysis["is_bullish"] == True)
            & (~df_analysis["pair"].isin(positions.keys()))
        ]

        if bullish_candidates.empty:
            bullish_candidates = df_analysis[
                ~df_analysis["pair"].isin(positions.keys())
            ]

        if not bullish_candidates.empty and balance >= min_buy_setting:
            target_buy_coin = bullish_candidates.iloc[0]
            buy_symbol = str(target_buy_coin["pair"])
            buy_price = float(target_buy_coin["last"])
            score = float(target_buy_coin["score"])

            calculated_amount = min_buy_setting + (max(score, 1.0) * 150)
            buy_amount_try = round(
                min(
                    max(calculated_amount, min_buy_setting),
                    max_buy_setting,
                    balance,
                ),
                2,
            )

            if (
                buy_amount_try >= min_buy_setting
                and buy_amount_try <= max_buy_setting
                and buy_price > 0
            ):
                coin_qty = buy_amount_try / buy_price
                new_balance = balance - buy_amount_try
                now_str = get_turkey_time()

                cursor.execute(
                    "UPDATE balance SET amount = ? WHERE id = 1", (new_balance,)
                )
                cursor.execute(
                    "INSERT INTO positions (pair, entry_price, highest_price, amount, cost, bought_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (buy_symbol, buy_price, buy_price, coin_qty, buy_amount_try, now_str),
                )
                cursor.execute(
                    "INSERT INTO history (pair, type, price, pnl, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        buy_symbol,
                        "ALIM",
                        f"₺{buy_price:,.2f}",
                        "₺0.00",
                        f"Dinamik Alım Yapıldı (Tutar: ₺{buy_amount_try:,.2f} | F&G: {fng_val})",
                        now_str,
                    ),
                )

    conn.commit()
    conn.close()


# 2. 7/24 KESİNTİSİZ ARKA PLAN ÇALIŞMASI (THREADING)
def start_background_bot():
    """Sekme kapalı olsa bile sunucu/arka plan üzerinde 10 sn'de bir döngüyü çalıştırır."""
    while True:
        try:
            run_aquiver_bot_cycle()
        except Exception:
            pass
        time.sleep(10)


if "bot_thread_started" not in st.session_state:
    st.session_state.bot_thread_started = True
    t = threading.Thread(target=start_background_bot, daemon=True)
    t.start()


# --- ARAYÜZ (STREAMLIT) ---
@st.fragment(run_every=5)
def live_dashboard():
    df_analysis = fetch_btcturk_analysis()
    balance, bot_positions, trade_history_df, current_min_buy, current_max_buy = (
        get_db_data()
    )
    fng_val, fng_text = fetch_fear_and_greed_index()

    if df_analysis.empty:
        st.warning("BtcTurk API verisi alınamadı, bekleniyor...")
        return

    pairs_list = df_analysis["pair"].tolist()

    if "selected_coin" not in st.session_state:
        st.session_state.selected_coin = pairs_list[0]

    if st.session_state.selected_coin not in pairs_list:
        st.session_state.selected_coin = pairs_list[0]

    total_unrealized_pnl = 0.0
    total_positions_current_val = 0.0
    pos_list = []
    for p_coin, p_data in bot_positions.items():
        if p_data["cost"] <= 0 or p_data["amount"] <= 0:
            continue

        c_match = df_analysis[df_analysis["pair"] == p_coin]
        if not c_match.empty:
            c_price = float(c_match.iloc[0]["last"])
            p_margin = float(c_match.iloc[0]["profit_margin"])
            s_margin = float(c_match.iloc[0]["stop_margin"])

            entry_p = float(p_data["entry_price"])
            cost_p = float(p_data["cost"])

            target_tp_price = entry_p * (1 + (p_margin / 100))
            target_tp_tl = cost_p * (p_margin / 100)

            target_sl_price = entry_p * (1 - (s_margin / 100))
            target_sl_tl = cost_p * (s_margin / 100)

            c_val = p_data["amount"] * c_price
            pnl = c_val - cost_p
            total_unrealized_pnl += pnl
            total_positions_current_val += c_val
            pnl_sign = "+" if pnl > 0 else ""

            current_portfolio_value = cost_p + pnl

            pos_list.append(
                {
                    "current_portfolio_value": current_portfolio_value,
                    "Coin": p_coin,
                    "Alış Fiyatı": f"₺{entry_p:,.2f}",
                    "Güncel Fiyat": f"₺{c_price:,.2f}",
                    "Yatırılan Tutar": f"₺{cost_p:,.2f}",
                    "Hedef Kâr (% / ₺)": f"%{p_margin:.1f} (+₺{target_tp_tl:,.2f})",
                    "Satış Fiyatı (Kâr)": f"₺{target_tp_price:,.2f}",
                    "Stop Loss (% / ₺)": f"-%{s_margin:.1f} (-₺{target_sl_tl:,.2f})",
                    "Stop Fiyatı (Zarar)": f"₺{target_sl_price:,.2f}",
                    "Anlık Kâr/Zarar": f"{pnl_sign}₺{pnl:,.2f}",
                    "Alım Zamanı": p_data.get("bought_at", "—"),
                }
            )

    selected_pair = st.session_state.selected_coin
    coin_data = df_analysis[df_analysis["pair"] == selected_pair].iloc[0]
    price, high, low = (
        coin_data["last"],
        coin_data["high"],
        coin_data["low"],
    )

    btc_match = df_analysis[df_analysis["pair"] == "BTCTRY"]
    btc_status = btc_match.iloc[0]["is_bullish"] if not btc_match.empty else True

    st.markdown("---")
    st.subheader("🤖 AquiverAI Sanal TRY Portföyü & Risk Göstergeleri")
    
    # Metrikleri Göster
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Kasadaki Sanal Bakiye", f"₺{balance:,.2f}")
    b2.metric("BTC Trend Durumu", "🟢 Pozitif" if btc_status else "🔴 Negatif (Acil Stop Etkin)")

    # Piyasa Psikolojisi Durum Metni
    if fng_val > 80:
        fng_display = f"🔥 {fng_val}/100 - Aşırı Açgözlülük (Alımlar Kilitlendi)"
    elif fng_val < 20:
        fng_display = f"😱 {fng_val}/100 - Aşırı Korku (Zarardakiler Kapatılıyor)"
    else:
        fng_display = f"⚖️ {fng_val}/100 - {fng_text}"

    b3.metric("Piyasa Psikolojisi (F&G)", fng_display)

    total_portfolio_val = balance + total_positions_current_val
    net_total_pnl = total_portfolio_val - 100000.0
    pnl_delta_str = f"+₺{net_total_pnl:,.2f}" if net_total_pnl >= 0 else f"-₺{abs(net_total_pnl):,.2f}"

    b4.metric(
        "Genel Toplam Kâr/Zarar",
        f"₺{net_total_pnl:,.2f}",
        delta=pnl_delta_str,
        delta_color="normal",
    )

    st.markdown("---")
    st.success(f"📊 **BtcTurk Hesabınızın Toplam Tahmini Değeri: ₺{total_portfolio_val:,.2f}**")

    if pos_list:
        st.subheader("⚡ Aktif Açık Pozisyonlar & Hedef / Stop Seviyeleri")
        df_pos = pd.DataFrame(pos_list)
        df_pos = df_pos.sort_values(by="current_portfolio_value", ascending=False)
        df_pos = df_pos.drop(columns=["current_portfolio_value"])
        st.dataframe(df_pos, use_container_width=True)

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    col1.metric("Son Fiyat", f"₺{price:,.2f}")
    col2.metric("24s En Yüksek", f"₺{high:,.2f}")
    col3.metric("24s En Düşük", f"₺{low:,.2f}")

    if not trade_history_df.empty:
        st.subheader("📜 AquiverAI İşlem Geçmişi (TSİ)")
        st.dataframe(trade_history_df, use_container_width=True)


df_initial = fetch_btcturk_analysis()
if not df_initial.empty:
    pairs_list = df_initial["pair"].tolist()

    if "selected_coin" not in st.session_state:
        st.session_state.selected_coin = pairs_list[0]

    st.sidebar.markdown("---")
    st.sidebar.subheader("📌 Coin Seçimi (Sadece TRY)")
    st.sidebar.selectbox(
        "Analiz Edilecek TRY Çifti:",
        pairs_list,
        key="coin_selector_box",
    )

    if st.sidebar.button("🔄 Kasayı ₺100,000'a Sıfırla"):
        reset_db()
        st.rerun()

live_dashboard()
