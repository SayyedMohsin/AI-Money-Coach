from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import datetime
import io
import csv
from fastapi.responses import Response
import google.generativeai as genai

# AAPKI GEMINI API KEY YAHAN DALEIN
GEMINI_API_KEY = "AAPKI_API_KEY_YAHAN_DALEIN"
genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="AI Money Coach API")

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

class Transaction(BaseModel):
    type: str
    category: str
    amount: float
    note: str = ""
    date: str = None

class ChatRequest(BaseModel):
    question: str

# Har user ka data alag filter karne ke liye
def get_financial_summary(session_id: str):
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    
    today = datetime.date.today()
    current_month_prefix = today.strftime("%Y-%m")
    first_day_of_month = today.replace(day=1).strftime("%Y-%m-%d")
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Income' AND date < ? AND session_id=?", (first_day_of_month, session_id))
    past_income = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date < ? AND session_id=?", (first_day_of_month, session_id))
    past_expense = cursor.fetchone()[0] or 0.0
    
    carry_forward_balance = past_income - past_expense

    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Income' AND date LIKE ? AND session_id=?", (f"{current_month_prefix}%", session_id))
    monthly_income = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=?", (f"{current_month_prefix}%", session_id))
    monthly_expense = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT COUNT(DISTINCT date) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=?", (f"{current_month_prefix}%", session_id))
    unique_days = cursor.fetchone()[0] or 1
    
    conn.close()
    
    current_balance = carry_forward_balance + monthly_income - monthly_expense
    avg_daily_expense = monthly_expense / unique_days if unique_days > 0 else 0
    days_left = int(current_balance / avg_daily_expense) if avg_daily_expense > 0 else 999
        
    return {
        "carry_forward": carry_forward_balance,
        "monthly_income": monthly_income,
        "total_expense": monthly_expense,
        "current_balance": current_balance,
        "avg_daily_expense": avg_daily_expense,
        "days_left": days_left,
        "current_month": current_month_prefix
    }

# API Endpoints (Ab sab me Header se session_id aayega)
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
    return {"message": "Entry added"}

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
        "month": year_month, "total_income": total_inc, "total_expense": total_exp,
        "category_breakdown": [dict(row) for row in categories], "transactions": [dict(row) for row in transactions]
    }

@app.get("/download-csv/{year_month}")
def download_csv(year_month: str, x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT date, type, category, amount, note FROM transactions WHERE date LIKE ? AND session_id=? ORDER BY date ASC", (f"{year_month}%", x_session_id))
    transactions = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Category", "Amount", "Note"])
    t_inc = t_exp = 0
    for t in transactions:
        writer.writerow([t[0], t[1], t[2], t[3], t[4]])
        if t[1] == 'Income': t_inc += t[3]
        if t[1] == 'Expense': t_exp += t[3]
        
    writer.writerow([])
    writer.writerow(["", "", "Total Income", t_inc, ""])
    writer.writerow(["", "", "Total Expense", t_exp, ""])
    writer.writerow(["", "", "Net Balance", t_inc - t_exp, ""])
    
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=MoneyCoach_Invoice_{year_month}.csv"
    return response

@app.delete("/clear-db")
def clear_database(x_session_id: str = Header(None)):
    conn = sqlite3.connect("finance_data.db")
    cursor = conn.cursor()
    # Sirf us user ka data delete hoga jisne click kiya hai!
    cursor.execute("DELETE FROM transactions WHERE session_id=?", (x_session_id,))
    conn.commit()
    conn.close()
    return {"message": "Data cleared"}

# Same AI Engine as before (removed long prompt for brevity, paste your previous prompt here)
@app.post("/chat")
def chat_with_ai(request: ChatRequest, x_session_id: str = Header(None)):
    try:
        if GEMINI_API_KEY == "AAPKI_API_KEY_YAHAN_DALEIN":
            return {"reply": "Backend mein pehle apni Gemini API Key dalein!"}
            
        summary = get_financial_summary(x_session_id)
        conn = sqlite3.connect("finance_data.db")
        cursor = conn.cursor()
        current_month = datetime.date.today().strftime("%Y-%m")
        cursor.execute("SELECT category, SUM(amount) FROM transactions WHERE type='Expense' AND date LIKE ? AND session_id=? GROUP BY category", (f"{current_month}%", x_session_id))
        categories = cursor.fetchall()
        conn.close()
        
        cat_str = "\n".join([f"{row[0]}: ₹{row[1]}" for row in categories]) if categories else "Koi kharcha nahi."
        
        prompt = f"""
        Aap ek expert Indian financial advisor hain. User ka data dekhein aur Hinglish me unke sawal ka jawab dein.
        Bacha Hua Paisa: ₹{summary['current_balance']}
        Kul Kharcha: ₹{summary['total_expense']}
        Roz ka average: ₹{summary['avg_daily_expense']:.2f}
        Kharche: {cat_str}
        User ka sawal: {request.question}
        """
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
