Empaquetar el código:
pyinstaller --onefile --windowed `
  --icon="icon.ico" `
  --add-data "gato2.jpeg;." `
  --name "CSV_a_Google_Calendar" `
  csv_a_google_calendar.py
