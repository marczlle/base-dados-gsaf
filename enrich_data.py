import os
import time
from datetime import datetime
import numpy as np
import pandas as pd
from geopy.geocoders import ArcGIS
import openmeteo_requests
import requests_cache
from retry_requests import retry

# --- CONFIGURAÇÕES INICIAIS ---
ARQUIVO_ENTRADA = "GSAF_clean.csv"
ARQUIVO_SAIDA = "GSAF_clima.csv" # Nome novo para a base padronizada
ARQUIVO_LOG = "erros_mineracao.txt"

cache_session = requests_cache.CachedSession('.cache_weather', expire_after=86400)
retry_session = retry(cache_session, retries=3, backoff_factor=1)
openmeteo = openmeteo_requests.Client(session=retry_session)

geolocator = ArcGIS(user_agent="sharkguard_tcc_mining")

MESES_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04', 'may': '05', 'jun': '06',
    'jul': '07', 'aug': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    'september': '09'
}

def registrar_erro(mensagem):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ARQUIVO_LOG, 'a', encoding='utf-8') as f:
        f.write(f"[{agora}] {mensagem}\n")

def formatar_data_api(ano, mes, dia):
    try:
        ano_str = str(int(float(ano)))
        if int(ano_str) < 1940: return None
        mes_limpo = str(mes).strip().lower()
        mes_str = MESES_MAP.get(mes_limpo[:3], None)
        if not mes_str:
            if mes_limpo.isdigit(): mes_str = mes_limpo.zfill(2)
            else: return None
        dia_limpo = str(dia).strip().lower()
        if 'unknown' in dia_limpo or not dia_limpo.isdigit(): dia_str = "01"
        else: dia_str = dia_limpo.zfill(2)
        return f"{ano_str}-{mes_str}-{dia_str}"
    except:
        return None

def buscar_coordenadas_robustas(localidade, estado, pais):
    loc = localidade if str(localidade).lower() != 'unknown' else ""
    est = estado if str(estado).lower() != 'unknown' else ""
    pai = pais if str(pais).lower() != 'unknown' else ""
    buscas = []
    if loc and est and pai: buscas.append(f"{loc}, {est}, {pai}")
    if loc and pai: buscas.append(f"{loc}, {pai}")
    if est and pai: buscas.append(f"{est}, {pai}")
    buscas = list(dict.fromkeys(buscas))
    
    for string_busca in buscas:
        if not string_busca.strip(): continue
        try:
            print(f"    -> Mapa: '{string_busca}'...")
            local = geolocator.geocode(string_busca, timeout=10)
            if local: return local.latitude, local.longitude, string_busca
        except: pass 
        time.sleep(1) 
    return np.nan, np.nan, None

def buscar_clima_historico(lat, lon, data_formatada):
    while True:
        try:
            url_archive = "https://archive-api.open-meteo.com/v1/archive"
            params_archive = {
                "latitude": lat, 
                "longitude": lon,
                "start_date": data_formatada, 
                "end_date": data_formatada,
                "daily": ["temperature_2m_mean", "precipitation_sum", "wind_speed_10m_max", "wind_direction_10m_dominant"]
            }
            
            resps = openmeteo.weather_api(url_archive, params=params_archive)
            daily = resps[0].Daily()
            
            temp_ar = daily.Variables(0).ValuesAsNumpy()[0]
            precip = daily.Variables(1).ValuesAsNumpy()[0]
            wind_speed = daily.Variables(2).ValuesAsNumpy()[0]
            wind_dir = daily.Variables(3).ValuesAsNumpy()[0]

            return temp_ar, precip, wind_speed, wind_dir

        except Exception as e:
            erro_str = str(e).lower()
            if "429" in erro_str or "too many requests" in erro_str or "limit" in erro_str or "retryerror" in erro_str:
                msg = "Limite da API atingido. Pausando 15 minutos..."
                registrar_erro(msg)
                print(f"    [!] {msg}")
                time.sleep(900)
                continue
            else:
                return np.nan, np.nan, np.nan, np.nan

def processar_base():
    if not os.path.exists(ARQUIVO_ENTRADA): 
        print(f"[-] Erro: {ARQUIVO_ENTRADA} não encontrado.")
        return

    df_original = pd.read_csv(ARQUIVO_ENTRADA)
    total_linhas = len(df_original)
    
    linhas_completadas = 0
    if os.path.exists(ARQUIVO_SAIDA):
        df_progresso = pd.read_csv(ARQUIVO_SAIDA)
        linhas_completadas = len(df_progresso)
        print(f"[!] Retomando: Pulando {linhas_completadas} linhas do {ARQUIVO_SAIDA}.")
    
    for idx in range(linhas_completadas, total_linhas):
        row = df_original.iloc[idx].copy()
        print(f"\n[{idx + 1}/{total_linhas}] Index {idx}")

        lat, lon, sucesso_str = buscar_coordenadas_robustas(row.get('Location'), row.get('State'), row.get('Country'))
        temp_ar, precip, wind_speed, wind_dir = np.nan, np.nan, np.nan, np.nan

        if not pd.isna(lat):
            print(f"    [+] OK Coord: Lat {lat:.4f} / Lon {lon:.4f} (Via: {sucesso_str})")
            data_formatada = formatar_data_api(row.get('Year'), row.get('Month'), row.get('Day'))
            
            if data_formatada:
                temp_ar, precip, wind_speed, wind_dir = buscar_clima_historico(lat, lon, data_formatada)
                
                if not np.isnan(temp_ar):
                    print(f"    [+] OK Clima: {data_formatada} | Temp: {temp_ar:.1f}°C | Chuva: {precip:.1f}mm | Vento: {wind_speed:.1f}km/h")
                else:
                    print("    [-] Falha Clima: API não retornou dados.")
            else:
                 print("    [-] Ignorado: Data inválida ou antes de 1940.")
        else:
             print("    [-] Falha Coord: Localização não decifrada.")

        row['extracted_lat'] = lat
        row['extracted_lon'] = lon
        row['temperature_2m_mean'] = temp_ar
        row['precipitation_sum'] = precip
        row['wind_speed_10m_max'] = wind_speed
        row['wind_direction_10m_dominant'] = wind_dir

        df_linha = pd.DataFrame([row])
        if not os.path.exists(ARQUIVO_SAIDA): df_linha.to_csv(ARQUIVO_SAIDA, index=False)
        else: df_linha.to_csv(ARQUIVO_SAIDA, mode='a', header=False, index=False)
            
        time.sleep(1) # Pode ser menor agora que fazemos só 1 request

if __name__ == "__main__":
    processar_base()