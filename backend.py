from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import datetime
from typing import List, Optional
from fastapi.responses import Response
import csv
import io

app = FastAPI(title="AI Money Coach API")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Setup (Naya 'session_id' column add kiya hai)
def init_db():
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            date TEXT,
            type TEXT,
            category TEXT,
            amount REAL,
            note TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Pydantic Models
class Transaction(BaseModel):
    type: str
    category: str
    amount: float
    note: str = ""
    date: Optional[str] = None

class ChatRequest(BaseModel):
    question: str

# Helper Function: Har user ka data alag filter karne ke liye
def get_financial_summary(session_id: str):
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    
    today = datetime.date.today()
    current_month_prefix = today.strftime("%Y-%m")
    first_day_of_month = today.replace(day=1).strftime("%Y-%m-%d")
    
    # 1. Pichle mahine tak ka bacha hua paisa
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Income' AND date < ? AND session_id=?", (first_day_of_month, session_id))
    past_income = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date < ? AND session_id=?", (first_day_of_month, session_id))
    past_expense = cursor.fetchone()[0] or 0.0
    
    carry_forward_balance = past_income - past_expense

    # 2. Is mahine ki aamdani aur kharcha
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Income' AND date LIKE ? AND session_id=?", (f"{current_month_prefix}%", session_id))
    monthly_income = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=?", (f"{current_month_prefix}%", session_id))
    monthly_expense = cursor.fetchone()[0] or 0.0
    
    # Is mahine ke unique days
    cursor.execute("SELECT COUNT(DISTINCT date) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=?", (f"{current_month_prefix}%", session_id))
    unique_days = cursor.fetchone()[0] or 1
    
    conn.close()
    
    # Total Balance
    current_balance = carry_forward_balance + monthly_income - monthly_expense
    
    # Roz ka kharcha
    avg_daily_expense = monthly_expense / unique_days if unique_days > 0 else 0
    
    if avg_daily_expense > 0:
        days_left = int(current_balance / avg_daily_expense)
    else:
        days_left = 999
        
    return {
        "carry_forward": carry_forward_balance,
        "monthly_income": monthly_income,
        "total_expense": monthly_expense,
        "current_balance": current_balance,
        "avg_daily_expense": avg_daily_expense,
        "days_left": days_left,
        "current_month": current_month_prefix
    }

# API Endpoints
@app.get("/summary")
def summary(x_session_id: str = Header(None)):
    return get_financial_summary(x_session_id)

@app.post("/transactions")
def add_transaction(t: Transaction, x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    selected_date = t.date if t.date else datetime.date.today().strftime("%Y-%m-%d")
    cursor.execute(
        "INSERT INTO transactions (session_id, date, type, category, amount, note) VALUES (?, ?, ?, ?, ?, ?)",
        (x_session_id, selected_date, t.type, t.category, t.amount, t.note)
    )
    conn.commit()
    conn.close()
    return {"message": "Entry successfully add ho gayi!"}

@app.get("/transactions")
def get_transactions(x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE session_id=? ORDER BY date DESC, id DESC", (x_session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/monthly-report/{year_month}")
def get_monthly_report(year_month: str, x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM transactions WHERE date LIKE ? AND session_id=? ORDER BY date ASC", (f"{year_month}%", x_session_id))
    transactions = cursor.fetchall()
    
    cursor.execute("SELECT category, SUM(amount) as total FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=? GROUP BY category", (f"{year_month}%", x_session_id))
    categories = cursor.fetchall()
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=?", (f"{year_month}%", x_session_id))
    total_exp = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Income' AND date LIKE ? AND session_id=?", (f"{year_month}%", x_session_id))
    total_inc = cursor.fetchone()[0] or 0.0
    
    conn.close()
    
    return {
        "month": year_month,
        "total_income": total_inc,
        "total_expense": total_exp,
        "category_breakdown": [dict(row) for row in categories],
        "transactions": [dict(row) for row in transactions]
    }

@app.get("/download-csv/{year_month}")
def download_csv(year_month: str, x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT date, type, category, amount, note FROM transactions WHERE date LIKE ? AND session_id=? ORDER BY date ASC", (f"{year_month}%", x_session_id))
    transactions = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Category", "Amount", "Note"])
    
    t_inc = 0
    t_exp = 0
    for t in transactions:
        writer.writerow([t['date'], t['type'], t['category'], t['amount'], t['note']])
        if t['type'] == 'Income': t_inc += t['amount']
        if t['type'] == 'Expense': t_exp += t['amount']
        
    writer.writerow([])
    writer.writerow(["", "", "Total Income", t_inc, ""])
    writer.writerow(["", "", "Total Expense", t_exp, ""])
    writer.writerow(["", "", "Net Balance", t_inc - t_exp, ""])
    
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=MoneyCoach_Invoice_{year_month}.csv"
    return response

# UPGRADED BILINGUAL AI ENGINE (English + Hinglish Smart Detection)
def generate_internal_advice(question: str, summary: dict, categories: list):
    q = question.lower()
    
    hinglish_keywords = ["kya", "kitna", "kahan", "kharcha", "bacha", "batao", "kaise", "mera", "paise", "kare", "karna"]
    is_hinglish = any(word in q for word in hinglish_keywords)
    
    top_category = "None"
    top_amount = 0
    if categories:
        sorted_cats = sorted(categories, key=lambda x: x[1], reverse=True)
        top_category = sorted_cats[0][0]
        top_amount = sorted_cats[0][1]

    if is_hinglish:
        if any(word in q for word in ["kharcha", "spend", "udaya", "expense"]):
            return f"Aapne is mahine total ₹{summary['total_expense']} kharch kiye hain. Sabse zyada paisa '{top_category}' (₹{top_amount}) par laga hai. Ispe control karein."
        elif any(word in q for word in ["bacha", "save", "savings", "kam kare", "balance"]):
            return f"Aapka current balance ₹{summary['current_balance']} hai. Pichle mahine ka bacha hua ₹{summary['carry_forward']} bhi isme included hai. Badi shopping se bachein."
        elif any(word in q for word in ["invest", "nivesh", "kahan lagaye", "sip"]):
            return "Agar aapka balance ₹5000 se zyada hai, toh Index Mutual Funds mein SIP lagana best rahega. Agar kam hai, toh pehle Emergency fund banayein."
        elif any(word in q for word in ["report", "hisaab", "summary"]):
             return f"Is mahine ki aamdani ₹{summary['monthly_income']} aur kharcha ₹{summary['total_expense']} hai. Bacha hua balance ₹{summary['current_balance']} hai."
        else:
            return f"Main aapka AI assistant hu. Aapka balance ₹{summary['current_balance']} hai. Kripya expenses, savings ya investment par sawaal poochein."
    else:
        if any(word in q for word in ["expense", "spend", "spent", "cost"]):
            return f"Your total expense this month is ₹{summary['total_expense']}. Your highest spending category is '{top_category}' at ₹{top_amount}. Try to reduce this to save more."
        elif any(word in q for word in ["balance", "left", "save", "savings", "remaining"]):
            return f"Your current available balance is ₹{summary['current_balance']}. This includes ₹{summary['carry_forward']} carried over from past months."
        elif any(word in q for word in ["invest", "mutual fund", "sip", "grow"]):
            return "If your balance exceeds ₹5000, consider starting an SIP in Mutual Funds. Otherwise, focus on building an emergency fund first."
        elif any(word in q for word in ["report", "invoice", "summary"]):
             return f"This month's income is ₹{summary['monthly_income']} and total expense is ₹{summary['total_expense']}. Your net available balance is ₹{summary['current_balance']}."
        else:
            return f"I am your AI Financial Coach. Your current balance stands at ₹{summary['current_balance']}. Feel free to ask specifically about your expenses, savings, or investments."

@app.post("/chat")
def chat_with_ai(request: ChatRequest, x_session_id: str = Header(None)):
    try:
        summary = get_financial_summary(x_session_id)
        
        conn = sqlite3.connect("finance_data.db")
        cursor = conn.cursor()
        current_month = datetime.date.today().strftime("%Y-%m")
        cursor.execute("SELECT category, SUM(amount) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=? GROUP BY category", (f"{current_month}%", x_session_id))
        categories = cursor.fetchall()
        conn.close()
        
        smart_reply = generate_internal_advice(request.question, summary, categories)
        
        return {"reply": smart_reply}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Engine Error: {str(e)}")

# NAYA ENDPOINT: Database ko clear karne ke liye (Sirf ussi user ka jiska session ho)
@app.delete("/clear-db")
def clear_database(x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions WHERE session_id=?", (x_session_id,))
    conn.commit()
    conn.close()
    return {"message": "Aapka data successfully delete ho gaya hai!"}
