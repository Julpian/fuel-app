from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import pandas as pd
import os
from io import BytesIO
import openpyxl

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Constants
DATA_FILE = "fuel_data.csv"
LOCKED_UNITS = ["DR0011", "DR0025", "DZ1009", "DZ1022", "DZ3007", "DZ3014", "DZ3026", "EX409", "EX421", "GR2021", "GR2026", "GR2009", "GR2050", "LD0045", "LD0046", "LD0069", "LD0143", "LD0145", "LD0146", "LD0150", "LD0152"]
PENJATAHAN_MAP = {
    "DR0011": 62, "DR0025": 62, "DZ1009": 35, "DZ1022": 35, "DZ3007": 60, "DZ3014": 51, "DZ3026": 60,
    "EX409": 31, "EX421": 27, "GR2021": 30, "GR2026": 30, "GR2009": 30, "GR2050": 28,
    "LD0045": 11, "LD0046": 11, "LD0069": 11, "LD0143": 11, "LD0145": 11, "LD0146": 11, "LD0150": 11, "LD0152": 11
}

# Data Functions
def load_or_create_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    else:
        columns = ["NO_UNIT", "HM_AWAL", "HM_AKHIR", "SELISIH", "LITERAN", "PENJATAHAN"]
        return pd.DataFrame(columns=columns)

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

def reset_data():
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)

def backup_data():
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE)
        df.to_csv("backup_" + DATA_FILE, index=False)

def get_hm_awal(df, no_unit):
    unit_data = df[df["NO_UNIT"] == no_unit]
    if not unit_data.empty:
        return unit_data["HM_AKHIR"].iloc[-1]
    return 0

def get_penjatahan(no_unit):
    return PENJATAHAN_MAP.get(no_unit, 62)

def add_new_record(no_unit, hm_akhir):
    df = load_or_create_data()
    hm_awal = get_hm_awal(df, no_unit)
    penjatahan = get_penjatahan(no_unit)

    if hm_akhir <= hm_awal:
        return df, None, f"HM Akhir ({hm_akhir}) harus lebih besar dari HM Awal ({hm_awal})!"

    selisih = hm_akhir - hm_awal
    literan = selisih * penjatahan

    new_record = {
        "NO_UNIT": no_unit,
        "HM_AWAL": hm_awal,
        "HM_AKHIR": hm_akhir,
        "SELISIH": selisih,
        "LITERAN": literan,
        "PENJATAHAN": penjatahan
    }

    df = pd.concat([df, pd.DataFrame([new_record])], ignore_index=True)
    save_data(df)
    return df, new_record, None

@app.route("/", methods=["GET", "POST"])
def index():
    df = load_or_create_data()
    selected_unit = request.form.get("selected_unit", LOCKED_UNITS[0])
    hm_akhir = request.form.get("hm_akhir")
    filter_unit = request.form.get("filter_unit", "Semua")
    error = None
    success = None
    new_literan = None

    # Handle form submission
    if request.method == "POST" and "submit_data" in request.form:
        try:
            hm_akhir = float(hm_akhir)
            if hm_akhir - get_hm_awal(df, selected_unit) > 24:
                flash(f"Selisih HM {hm_akhir - get_hm_awal(df, selected_unit)} terlalu besar. Pastikan input benar!", "warning")
            df, new_record, error = add_new_record(selected_unit, hm_akhir)
            if error:
                flash(error, "error")
            else:
                flash(f"Data untuk unit {selected_unit} berhasil disimpan!", "success")
                new_literan = new_record["LITERAN"]  # Simpan literan baru untuk ditampilkan
        except ValueError:
            flash("Masukkan HM Akhir yang valid!", "error")

    # Get last record for selected unit
    current_unit_data = df[df["NO_UNIT"] == selected_unit]
    last_hm_akhir = current_unit_data["HM_AKHIR"].iloc[-1] if not current_unit_data.empty else 0
    default_hm_akhir = last_hm_akhir + 1.0

    # Prepare historical data
    historical_data = df.to_dict(orient="records")

    return render_template(
        "index.html",
        units=LOCKED_UNITS,
        selected_unit=selected_unit,
        last_hm_akhir=last_hm_akhir,
        default_hm_akhir=default_hm_akhir,
        historical_data=historical_data,
        filter_unit=filter_unit,
        unique_units=sorted(df["NO_UNIT"].unique()) if not df.empty else LOCKED_UNITS,
        new_literan=new_literan
    )

@app.route("/download_all")
def download_all():
    df = load_or_create_data()
    if df.empty:
        flash("Tidak ada data untuk diunduh!", "error")
        return redirect(url_for("index"))

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    return send_file(
        output,
        download_name="fuel_data_all.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/download_unit/<unit>")
def download_unit(unit):
    df = load_or_create_data()
    df_unit = df[df["NO_UNIT"] == unit]
    if df_unit.empty:
        flash(f"Tidak ada data untuk unit {unit}!", "error")
        return redirect(url_for("index"))

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_unit.to_excel(writer, index=False)
    output.seek(0)

    return send_file(
        output,
        download_name=f"fuel_data_{unit}.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/reset", methods=["POST"])
def reset():
    backup_data()
    reset_data()
    flash("Semua data berhasil dihapus! Backup telah dibuat.", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)