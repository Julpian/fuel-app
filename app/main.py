from flask import Flask, render_template, request, redirect, url_for, send_file, flash, make_response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pandas as pd
import os
from io import BytesIO
import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask
app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey')

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize Supabase client
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("SUPABASE_URL or SUPABASE_KEY environment variable is not set")
    raise ValueError("SUPABASE_URL or SUPABASE_KEY environment variable is not set.")
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info(f"Connected to Supabase at {SUPABASE_URL}")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {str(e)}")
    raise RuntimeError(f"Failed to initialize Supabase client: {str(e)}")

# User model for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    try:
        response = supabase.table('users').select('*').eq('id', user_id).execute()
        if response.data:
            user_data = response.data[0]
            return User(user_data['id'], user_data['username'], user_data['role'])
        return None
    except Exception as e:
        logger.error(f"Error loading user: {str(e)}")
        return None

LOCKED_UNITS = [
    "DZ3007", "DZ3014", "DZ3026", "EX1022", "EX2017", "EX2027", "EX2032", "EX2033", "EX2040", "EX3009"
]
PENJATAHAN_MAP = {
    "DZ3007": 52, "DZ3014": 52, "DZ3026": 52,
    "EX1022": 58,
    "EX2017": 93, "EX2027": 93, "EX2032": 93, "EX2033": 93, "EX2040": 93,
    "EX3009": 126
}
MAX_CAPACITY_MAP = {
    "DZ3007": 1000, "DZ3014": 1000, "DZ3026": 1200,
    "EX1022": 980,
    "EX2017": 1380, "EX2027": 1380, "EX2032": 1380, "EX2033": 1380, "EX2040": 1380,
    "EX3009": 3400
}
INITIAL_HM_Awal = {
    "DZ3007": 45645, "DZ3014": 46203, "DZ3026": 20629,
    "EX1022": 34750,
    "EX2017": 46115, "EX2027": 35466, "EX2032": 27140, "EX2033": 26280, "EX2040": 19070,
    "EX3009": 36002
}

# Custom strftime filter
def format_datetime(value, format='%Y-%m-%d'):
    if value == 'now':
        return datetime.now().strftime(format)
    # Ensure value is a datetime object before formatting
    if isinstance(value, datetime):
        return value.strftime(format)
    return str(value) # Fallback to string conversion if not datetime

app.jinja_env.filters['strftime'] = format_datetime

# Helper functions
def load_or_create_data():
    """
    Loads fuel records from Supabase, processes them into a Pandas DataFrame,
    and ensures the DataFrame is sorted chronologically by Date and Shift.
    """
    try:
        response = supabase.table('fuel_records').select('*').execute()
        records = response.data
        if records:
            # Load records directly into DataFrame
            df = pd.DataFrame(records)

            # Ensure all required columns exist, adding them if missing
            required_cols = [
                "Date", "NO_UNIT", "HM_Awal", "HM_Akhir", "Selisih",
                "Literan", "Penjatahan", "Max_Capacity", "Buffer_Stock", "is_new", "shift"
            ]
            for col in required_cols:
                if col not in df.columns:
                    df[col] = None # Add missing columns with None

            # Convert column types and clean data
            # errors='coerce' will turn unparseable dates into NaT (Not a Time)
            df["Date"] = pd.to_datetime(df["Date"], errors='coerce') 
            df["NO_UNIT"] = df["NO_UNIT"].astype(str).str.strip()
            df["HM_Awal"] = df["HM_Awal"].astype(float).round(2)
            df["HM_Akhir"] = df["HM_Akhir"].astype(float).round(2)
            df["Selisih"] = df["Selisih"].astype(float).round(2)
            df["Literan"] = df["Literan"].astype(float).round(2)
            df["Penjatahan"] = df["Penjatahan"].astype(int)
            df["Max_Capacity"] = df["Max_Capacity"].astype(float).round(2)
            df["Buffer_Stock"] = df["Buffer_Stock"].astype(float).round(2)
            df["is_new"] = df["is_new"].astype(bool)
            # Ensure 'shift' is string and handle potential 'nan' values by replacing them with empty string
            df["shift"] = df["shift"].astype(str).str.strip().replace('nan', '')

            # Create a temporary 'shift_order' column for correct chronological sorting
            # 'Shift 1' gets 1, 'Shift 2' gets 2, any other values get 3 (placing them last)
            df['shift_order'] = df['shift'].map({'Shift 1': 1, 'Shift 2': 2}).fillna(3)

            # Sort the DataFrame by Date (ascending) then by shift_order (ascending)
            df = df.sort_values(by=['Date', 'shift_order'], ascending=[True, True])
            
            # Drop the temporary 'shift_order' column as it's no longer needed
            df = df.drop(columns=['shift_order'])

            return df
        
        # If no records are found in Supabase, return an empty DataFrame with correct columns
        columns = [
            "Date", "NO_UNIT", "HM_Awal", "HM_Akhir", "Selisih",
            "Literan", "Penjatahan", "Max_Capacity", "Buffer_Stock", "is_new", "shift"
        ]
        return pd.DataFrame(columns=columns)
    except Exception as e:
        logger.error(f"Error loading data from Supabase: {str(e)}")
        # Re-raise the exception or return an empty DataFrame with appropriate columns on error
        # Returning an empty DataFrame might prevent a full app crash
        return pd.DataFrame(columns=required_cols if 'required_cols' in locals() else [])

def save_data(df):
    """
    Saves the DataFrame back to Supabase. This function clears all existing records
    and then inserts all records from the DataFrame.
    """
    try:
        # Delete all existing records in Supabase (as per original logic)
        supabase.table('fuel_records').delete().gte('id', 0).execute()
        
        records_to_insert = []
        for _, row in df.iterrows():
            record = {
                # Convert datetime objects in 'Date' column back to string for Supabase
                "Date": row["Date"].strftime("%Y-%m-%d") if pd.notna(row["Date"]) else None,
                "NO_UNIT": str(row["NO_UNIT"]).strip(),
                "HM_Awal": float(row["HM_Awal"]),
                "HM_Akhir": float(row["HM_Akhir"]),
                "Selisih": float(row["Selisih"]),
                "Literan": float(row["Literan"]),
                "Penjatahan": int(row["Penjatahan"]),
                "Max_Capacity": float(row["Max_Capacity"]),
                "Buffer_Stock": float(row["Buffer_Stock"]),
                "is_new": bool(row["is_new"]),
                "shift": str(row.get("shift", "")).strip()
            }
            records_to_insert.append(record)
        
        # Perform a batch insert if there are records to insert
        if records_to_insert:
            supabase.table('fuel_records').insert(records_to_insert).execute()
    except Exception as e:
        logger.error(f"Error saving data to Supabase: {str(e)}")
        raise

def reset_data():
    try:
        supabase.table('fuel_records').delete().gte('id', 0).execute()
    except Exception as e:
        logger.error(f"Error resetting data in Supabase: {str(e)}")
        raise

def backup_data():
    df = load_or_create_data()
    if not df.empty:
        df.to_csv("backup_fuel_data.csv", index=False)

def get_hm_awal(df, no_unit):
    """
    Gets the last HM_Akhir for a given unit from the sorted DataFrame.
    If no records exist for the unit, it returns the initial HM_Awal.
    """
    # Since df is now guaranteed to be sorted chronologically by load_or_create_data(),
    # filtering and taking the last element will correctly give the latest HM_Akhir.
    unit_data = df[df["NO_UNIT"] == no_unit]
    if not unit_data.empty:
        return unit_data["HM_Akhir"].iloc[-1]
    return INITIAL_HM_Awal.get(no_unit, 0.0)

def get_penjatahan(no_unit):
    return PENJATAHAN_MAP.get(no_unit, 62)

def get_max_capacity(no_unit):
    return MAX_CAPACITY_MAP.get(no_unit, 0)

def add_new_record(no_unit, hm_akhir, date, shift):
    df = load_or_create_data() # Load the data, which is now sorted
    hm_awal = get_hm_awal(df, no_unit)
    penjatahan = get_penjatahan(no_unit)
    max_capacity = get_max_capacity(no_unit)

    if hm_akhir <= hm_awal:
        return df, None, f"HM Akhir ({hm_akhir}) harus lebih besar dari HM Awal ({hm_awal})!"

    selisih = hm_akhir - hm_awal
    selisih = round(selisih, 2)
    literan = selisih * penjatahan
    buffer_stock = max_capacity - (selisih * penjatahan)

    new_record = {
        "Date": date.strftime("%Y-%m-%d"), # Date is already a string here
        "NO_UNIT": no_unit.strip(),
        "HM_Awal": round(hm_awal, 2),
        "HM_Akhir": round(hm_akhir, 2),
        "Selisih": selisih,
        "Literan": round(literan, 2),
        "Penjatahan": penjatahan,
        "Max_Capacity": round(max_capacity, 2),
        "Buffer_Stock": round(buffer_stock, 2),
        "is_new": True,
        "shift": shift
    }
    
    # Convert 'Date' in new_record to datetime object before concatenating to df
    # This ensures consistency with the df loaded by load_or_create_data
    new_record_df = pd.DataFrame([new_record])
    new_record_df["Date"] = pd.to_datetime(new_record_df["Date"], errors='coerce')

    # Ensure 'shift' column exists in df before concatenation if it's new
    if "shift" not in df.columns:
        df["shift"] = ""
    
    df = pd.concat([df, new_record_df], ignore_index=True)
    
    # Re-sort the DataFrame after adding a new record to maintain chronological order
    # for the *next* call to get_hm_awal without reloading all data.
    # This is important if you plan to do multiple adds without a full page refresh.
    df['shift_order'] = df['shift'].map({'Shift 1': 1, 'Shift 2': 2}).fillna(3)
    df = df.sort_values(by=['Date', 'shift_order'], ascending=[True, True])
    df = df.drop(columns=['shift_order'])

    save_data(df) # Save the updated and sorted DataFrame
    return df, new_record, None

def create_pdf_report(df, shift, date):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()
    shift_display = (
        "Shift 1 (06:00–18:00 WITA)" if shift == "Shift 1" else
        "Shift 2 (18:00–06:00 WITA)" if shift == "Shift 2" else
        "Shift 1 & 2 (All Day)"
    )
    title = Paragraph(
        f"PLAN REFUELING UNIT TRACK {date.strftime('%b %Y').upper()}"
        f"<br/>{shift_display} Tgl: {date.strftime('%d %b %Y')}",
        styles['Title']
    )
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    data = [["Date", "Unit", "Shift", "Est HM Jam 12:00", "HM", "Qty Plan Refueling", "Note"]]
    for _, row in df.iterrows():
        qty_plan = f"{row['Literan']:.2f}" if row['Literan'] > 0 else "Full" if row['Buffer_Stock'] <= 0 else "-"
        shift_value = row.get("shift", "Unknown")
        # Ensure 'Date' is formatted correctly for PDF
        display_date = row["Date"].strftime("%Y-%m-%d") if pd.notna(row["Date"]) else ""
        data.append([
            display_date,
            row["NO_UNIT"],
            shift_value,
            f"{row['HM_Awal']:.2f}",
            f"{row['Selisih']:.2f}",
            qty_plan,
            ""
        ])

    col_widths = [80, 60, 60, 100, 60, 100, 100]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.goldenrod),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        unit = request.args.get('unit')
        logger.info(f"Redirecting authenticated user to index, unit: {unit}")
        return redirect(url_for('index', unit=unit) if unit else url_for('index'))
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        try:
            response = supabase.table('users').select('*').eq('username', username).execute()
            if response.data and len(response.data) > 0:
                user_data = response.data[0]
                if check_password_hash(user_data['password_hash'], password):
                    user = User(user_data['id'], user_data['username'], user_data['role'])
                    login_user(user)
                    unit = request.form.get('unit') or request.args.get('unit')
                    logger.info(f"Login successful for {username}, redirecting to index, unit: {unit}")
                    flash('Login berhasil!', 'success')
                    return redirect(url_for('index', unit=unit) if unit and unit in LOCKED_UNITS else url_for('index'))
                else:
                    logger.warning(f"Failed login attempt for {username}: incorrect password")
                    flash('Kata sandi salah.', 'error')
            else:
                logger.warning(f"Failed login attempt: user {username} not found")
                flash('Pengguna tidak ditemukan.', 'error')
        except Exception as e:
            logger.error(f"Error during login for {username}: {str(e)}")
            flash('Terjadi kesalahan saat login. Silakan coba lagi.', 'error')
    
    response = make_response(render_template('login.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Anda telah logout.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    try:
        df = load_or_create_data() # Now df is guaranteed to be sorted
        units = LOCKED_UNITS
        selected_unit = request.args.get('unit', units[0])
        logger.info(f"Received unit parameter: {request.args.get('unit')} | Selected unit: {selected_unit}")
        
        # Validasi selected_unit
        if selected_unit not in units:
            logger.warning(f"Invalid unit selected: {selected_unit}, defaulting to {units[0]}")
            selected_unit = units[0]
        
        # get_hm_awal now correctly fetches the latest HM_Akhir due to sorted df
        last_hm_akhir = get_hm_awal(df, selected_unit)

        filter_unit = request.args.get('filter_unit', 'Semua')
        if filter_unit == 'Semua':
            filtered_df = df
        else:
            filtered_df = df[df["NO_UNIT"] == filter_unit]

        unique_units = ['Semua'] + sorted(df["NO_UNIT"].unique().tolist()) if not df.empty else ['Semua']
        
        # Render template dengan header anti-cache
        response = make_response(render_template(
            'index.html',
            units=units,
            selected_unit=selected_unit,
            last_hm_akhir=last_hm_akhir,
            # Convert 'Date' column to string for display in the template table
            # Make a copy to avoid SettingWithCopyWarning if you modify the original df later
            filtered_df=filtered_df.copy().assign(Date=filtered_df['Date'].dt.strftime('%Y-%m-%d')).to_dict(orient='records'),
            filter_unit=filter_unit,
            unique_units=unique_units,
            current_user=current_user
        ))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}")
        flash("Gagal memuat data. Silakan coba lagi nanti.", 'error')
        # Return a fallback render in case of error
        return render_template(
            'index.html',
            units=LOCKED_UNITS,
            selected_unit=LOCKED_UNITS[0],
            last_hm_akhir=0.0,
            filtered_df=[],
            filter_unit='Semua',
            unique_units=['Semua'],
            current_user=current_user
        )

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if current_user.role != 'admin':
        flash('Hanya admin yang dapat mengakses halaman ini.', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        role = request.form['role']
        try:
            response = supabase.table('users').select('username').eq('username', username).execute()
            # Supabase select returns an object with a 'data' key which is a list
            if response.data and len(response.data) > 0: # Check if data is not empty
                flash('Username sudah ada.', 'error')
            else:
                password_hash = generate_password_hash(password, method='pbkdf2:sha256')
                supabase.table('users').insert({
                    'username': username,
                    'password_hash': password_hash,
                    'role': role
                }).execute()
                flash('Pengguna berhasil ditambahkan!', 'success')
                return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error during registration: {str(e)}")
            flash('Gagal menambahkan pengguna. Silakan coba lagi.', 'error')
    
    return render_template('register.html')

@app.route('/add_record', methods=['POST'])
@login_required
def add_record():
    try:
        no_unit = request.form['no_unit'].strip()
        hm_akhir = float(request.form['hm_akhir'])
        date = datetime.strptime(request.form['date'], '%Y-%m-%d')
        shift = request.form['shift']

        if shift not in ["Shift 1", "Shift 2"]:
            flash("Invalid shift type selected.", 'error')
            return redirect(url_for('index', unit=no_unit))

        df, record, error = add_new_record(no_unit, hm_akhir, date, shift)
        if error:
            flash(error, 'error')
        else:
            flash(
                f"Data untuk unit {no_unit} berhasil disimpan! "
                f"Shift: <span style='color:#facc15;font-weight:bold'>{shift}</span> | "
                f"Buffer Stock: <span style='color:#facc15;font-weight:bold'>{record['Buffer_Stock']:.2f}</span> | "
                f"Literan: <span style='color:#facc15;font-weight:bold'>{record['Literan']:.2f}</span>",
                'success'
            )
        return redirect(url_for('index', unit=no_unit))
    except Exception as e:
        logger.error(f"Error in add_record: {str(e)}")
        flash("Gagal menambahkan data. Silakan coba lagi.", 'error')
        return redirect(url_for('index', unit=request.form.get('no_unit', LOCKED_UNITS[0])))

@app.route('/export_all')
@login_required
def export_all():
    try:
        df = load_or_create_data()
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Ensure Date column is formatted as string for Excel export
            df_export = df.copy()
            df_export['Date'] = df_export['Date'].dt.strftime('%Y-%m-%d')
            df_export.to_excel(writer, index=False)
        output.seek(0)
        return send_file(output, download_name='fuel_data_all.xlsx', as_attachment=True)
    except Exception as e:
        logger.error(f"Error in export_all: {str(e)}")
        flash("Gagal mengekspor data. Silakan coba lagi.", 'error')
        return redirect(url_for('index'))

@app.route('/export_unit/<unit>')
@login_required
def export_unit(unit):
    try:
        df = load_or_create_data()
        df_unit = df[df["NO_UNIT"] == unit].copy() # Make a copy
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Ensure Date column is formatted as string for Excel export
            df_unit['Date'] = df_unit['Date'].dt.strftime('%Y-%m-%d')
            df_unit.to_excel(writer, index=False)
        output.seek(0)
        return send_file(output, download_name=f'fuel_data_{unit}.xlsx', as_attachment=True)
    except Exception as e:
        logger.error(f"Error in export_unit: {str(e)}")
        flash("Gagal mengekspor data unit. Silakan coba lagi.", 'error')
        return redirect(url_for('index'))

@app.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf():
    try:
        report_date = datetime.strptime(request.form['report_date'], '%Y-%m-%d')
        shift = request.form['shift']
        valid_shifts = ["Shift 1", "Shift 2", "Both"]
        if shift not in valid_shifts:
            flash("Shift tidak valid. Pilih Shift 1, Shift 2, atau Both.", 'error')
            return redirect(url_for('index'))

        df = load_or_create_data() # df is now sorted
        if "shift" not in df.columns:
            df["shift"] = ""
        
        if shift == "Both":
            # Filter by date only, then sort by shift for consistent PDF output
            report_df = df[df["Date"] == report_date].copy()
            report_df['shift_order'] = report_df['shift'].map({'Shift 1': 1, 'Shift 2': 2}).fillna(3)
            report_df = report_df.sort_values(by='shift_order').drop(columns=['shift_order'])
        else:
            report_df = df[(df["Date"] == report_date) & (df["shift"] == shift)].copy()

        if not report_df.empty:
            pdf_buffer = create_pdf_report(report_df, shift, report_date)
            shift_display = "Shift1_0600-1800" if shift == "Shift 1" else "Shift2_1800-0600" if shift == "Shift 2" else "Both_Shifts"
            return send_file(
                pdf_buffer,
                download_name=f"Plan_Refueling_Hauler_{report_date.strftime('%d_%b_%Y')}_{shift_display}.pdf",
                as_attachment=True
            )
        else:
            flash(f"Tidak ada data untuk tanggal {report_date.strftime('%d %b %Y')} dan shift {shift}.", 'error')
            return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error in generate_pdf: {str(e)}")
        flash("Gagal menghasilkan PDF. Silakan coba lagi.", 'error')
        return redirect(url_for('index'))

@app.route('/reset_data', methods=['POST'])
@login_required
def reset_data_route():
    if current_user.role != 'admin':
        flash('Hanya admin yang dapat mereset data.', 'error')
        return redirect(url_for('index'))
    try:
        backup_data()
        reset_data()
        flash("Semua data berhasil dihapus! Backup telah dibuat.", 'success')
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error in reset_data: {str(e)}")
        flash("Gagal mereset data. Silakan coba lagi.", 'error')
        return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

