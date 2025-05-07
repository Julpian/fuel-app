from flask import Flask, render_template, request, redirect, url_for, send_file, flash
import pandas as pd
import os
from io import BytesIO
import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey')

# Tambahkan filter kustom strftime
def format_datetime(value, format='%Y-%m-%d'):
    if value == 'now':
        return datetime.now().strftime(format)
    return value.strftime(format)

app.jinja_env.filters['strftime'] = format_datetime

# Konstanta
DATABASE_URL = os.environ.get('DATABASE_URL')  # Ambil dari Vercel env
Base = declarative_base()
LOCKED_UNITS = ["DR0011", "DR0025", "DZ1009", "DZ1022", "DZ3007", "DZ3014", "DZ3026", "EX409", "EX421", "GR2021", "GR2026", "GR2009", "GR2050", "LD0045", "LD0046", "LD0069", "LD0143", "LD0145", "LD0146", "LD0150", "LD0152"]
PENJATAHAN_MAP = {
    "DR0011": 62, "DR0025": 62, "DZ1009": 35, "DZ1022": 35, "DZ3007": 60, "DZ3014": 51, "DZ3026": 60,
    "EX409": 31, "EX421": 27, "GR2021": 30, "GR2026": 30, "GR2009": 30, "GR2050": 28,
    "LD0045": 11, "LD0046": 11, "LD0069": 11, "LD0143": 11, "LD0145": 11, "LD0146": 11, "LD0150": 11, "LD0152": 10
}
MAX_CAPACITY_MAP = {
    "DR0011": 800, "DR0025": 800, "DZ1009": 0, "DZ1022": 0, "DZ3007": 0, "DZ3014": 0, "DZ3026": 0,
    "EX409": 0, "EX421": 0, "GR2021": 0, "GR2026": 0, "GR2009": 0, "GR2050": 0,
    "LD0045": 0, "LD0046": 0, "LD0069": 0, "LD0143": 0, "LD0145": 0, "LD0146": 0, "LD0150": 0, "LD0152": 250
}
INITIAL_HM_AWAL = {
    "DR0011": 100.0, "DR0025": 150.0, "DZ1009": 50.0, "DZ1022": 50.0, "DZ3007": 200.0, "DZ3014": 180.0,
    "DZ3026": 200.0, "EX409": 80.0, "EX421": 70.0, "GR2021": 90.0, "GR2026": 90.0, "GR2009": 90.0,
    "GR2050": 85.0, "LD0045": 30.0, "LD0046": 30.0, "LD0069": 30.0, "LD0143": 30.0, "LD0145": 30.0,
    "LD0146": 30.0, "LD0150": 30.0, "LD0152": 25.0
}

# Definisikan model database
class FuelRecord(Base):
    __tablename__ = 'fuel_records'
    id = Column(Integer, primary_key=True)
    Date = Column(String)
    NO_UNIT = Column(String)
    HM_AWAL = Column(Float)
    HM_AKHIR = Column(Float)
    SELISIH = Column(Float)
    LITERAN = Column(Float)
    PENJATAHAN = Column(Integer)
    Max_Capacity = Column(Float)
    Buffer_Stock = Column(Float)
    is_new = Column(Boolean, default=False)

# Inisialisasi database
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Data Functions
def load_or_create_data():
    session = Session()
    try:
        records = session.query(FuelRecord).all()
        if records:
            df = pd.DataFrame([
                {
                    "Date": r.Date,
                    "NO_UNIT": r.NO_UNIT,
                    "HM_AWAL": r.HM_AWAL,
                    "HM_AKHIR": r.HM_AKHIR,
                    "SELISIH": r.SELISIH,
                    "LITERAN": r.LITERAN,
                    "PENJATAHAN": r.PENJATAHAN,
                    "Max Capacity": r.Max_Capacity,
                    "Buffer Stock": r.Buffer_Stock,
                    "is_new": r.is_new
                } for r in records
            ])
            return df
        columns = ["Date", "NO_UNIT", "HM_AWAL", "HM_AKHIR", "SELISIH", "LITERAN", "PENJATAHAN", "Max Capacity", "Buffer Stock", "is_new"]
        return pd.DataFrame(columns=columns)
    finally:
        session.close()

def save_data(df):
    session = Session()
    try:
        session.query(FuelRecord).delete()
        for _, row in df.iterrows():
            record = FuelRecord(
                Date=row["Date"],
                NO_UNIT=row["NO_UNIT"],
                HM_AWAL=row["HM_AWAL"],
                HM_AKHIR=row["HM_AKHIR"],
                SELISIH=row["SELISIH"],
                LITERAN=row["LITERAN"],
                PENJATAHAN=row["PENJATAHAN"],
                Max_Capacity=row["Max Capacity"],
                Buffer_Stock=row["Buffer Stock"],
                is_new=row["is_new"]
            )
            session.add(record)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error saving data: {e}")
    finally:
        session.close()

def reset_data():
    session = Session()
    try:
        session.query(FuelRecord).delete()
        session.commit()
    finally:
        session.close()

def backup_data():
    df = load_or_create_data()
    if not df.empty:
        df.to_csv("/tmp/backup_fuel_data.csv", index=False)

def get_hm_awal(df, no_unit):
    unit_data = df[df["NO_UNIT"] == no_unit]
    if not unit_data.empty:
        return unit_data["HM_AKHIR"].iloc[-1]
    return INITIAL_HM_AWAL.get(no_unit, 0.0)

def get_penjatahan(no_unit):
    return PENJATAHAN_MAP.get(no_unit, 62)

def get_max_capacity(no_unit):
    return MAX_CAPACITY_MAP.get(no_unit, 0)

def add_new_record(no_unit, hm_akhir, date):
    df = load_or_create_data()
    hm_awal = get_hm_awal(df, no_unit)
    penjatahan = get_penjatahan(no_unit)
    max_capacity = get_max_capacity(no_unit)

    if hm_akhir <= hm_awal:
        return df, None, f"HM Akhir ({hm_akhir}) harus lebih besar dari HM Awal ({hm_awal})!"

    selisih = hm_akhir - hm_awal
    selisih = round(selisih, 1)
    literan = selisih * penjatahan
    buffer_stock = max_capacity - (selisih * penjatahan)

    new_record = {
        "Date": date.strftime("%Y-%m-%d"),
        "NO_UNIT": no_unit,
        "HM_AWAL": hm_awal,
        "HM_AKHIR": hm_akhir,
        "SELISIH": selisih,
        "LITERAN": literan,
        "PENJATAHAN": penjatahan,
        "Max Capacity": max_capacity,
        "Buffer Stock": buffer_stock,
        "is_new": True
    }

    df.loc[df["NO_UNIT"] == no_unit, "is_new"] = False
    df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
    save_data(df)
    return df, new_record, None

def create_pdf_report(df, shift, date):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()
    title = Paragraph(f"PLAN REFUELING UNIT HAULER OB PERIODE {date.strftime('%b %Y').upper()}<br/>Shift: {shift} Tgl: {date.strftime('%d %b %Y')}", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    data = [["Date", "UNIT", "Est HM Jam 12:00", "HM", "Qty Plan Refueling", "Note"]]
    for _, row in df.iterrows():
        qty_plan = f"{row['LITERAN']:.1f}" if row['LITERAN'] > 0 else "Full" if row['Buffer Stock'] <= 0 else "-"
        data.append([
            row["Date"],
            row["NO_UNIT"],
            f"{row['HM_AWAL']:.1f}",
            f"{row['SELISIH']:.1f}",
            qty_plan,
            ""
        ])

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.goldenrod),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

# Routes
@app.route('/')
def index():
    df = load_or_create_data()
    units = LOCKED_UNITS
    selected_unit = request.args.get('unit', units[0])
    current_unit_data = df[df["NO_UNIT"] == selected_unit]
    last_hm_akhir = get_hm_awal(df, selected_unit)

    filter_unit = request.args.get('filter_unit', 'Semua')
    if filter_unit == 'Semua':
        filtered_df = df
    else:
        filtered_df = df[df["NO_UNIT"] == filter_unit]
    
    unique_units = ['Semua'] + sorted(df["NO_UNIT"].unique().tolist()) if not df.empty else ['Semua']
    return render_template('index.html', units=units, selected_unit=selected_unit, last_hm_akhir=last_hm_akhir, 
                         filtered_df=filtered_df.to_dict(orient='records'), filter_unit=filter_unit, unique_units=unique_units)

@app.route('/add_record', methods=['POST'])
def add_record():
    no_unit = request.form['no_unit']
    hm_akhir = float(request.form['hm_akhir'])
    date = datetime.strptime(request.form['date'], '%Y-%m-%d')
    
    df, record, error = add_new_record(no_unit, hm_akhir, date)
    if error:
        flash(error, 'error')
    else:
        flash(f"Data untuk unit {no_unit} berhasil disimpan! Buffer Stock: <span class='text-yellow-400'>{record['Buffer Stock']}</span> | Literan: <span class='text-yellow-400'>{record['LITERAN']}</span>", 'success')
    return redirect(url_for('index', unit=no_unit))

@app.route('/export_all')
def export_all():
    df = load_or_create_data()
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name='fuel_data_all.xlsx', as_attachment=True)

@app.route('/export_unit/<unit>')
def export_unit(unit):
    df = load_or_create_data()
    df_unit = df[df["NO_UNIT"] == unit]
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_unit.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name=f'fuel_data_{unit}.xlsx', as_attachment=True)

@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    report_date = datetime.strptime(request.form['report_date'], '%Y-%m-%d')
    shift = request.form['shift']
    df = load_or_create_data()
    report_df = df[df["Date"] == report_date.strftime("%Y-%m-%d")]
    if not report_df.empty:
        pdf_buffer = create_pdf_report(report_df, shift, report_date)
        return send_file(pdf_buffer, download_name=f"Plan_Refueling_Hauler_{report_date.strftime('%d_%b_%Y')}_Shift_{shift}.pdf", as_attachment=True)
    else:
        flash(f"Tidak ada data untuk tanggal {report_date.strftime('%d %b %Y')}.", 'error')
        return redirect(url_for('index'))

@app.route('/reset_data', methods=['POST'])
def reset_data_route():
    backup_data()
    reset_data()
    flash("Semua data berhasil dihapus! Backup telah dibuat.", 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
