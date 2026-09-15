import pandas as pd
import numpy as np
import ephem
from datetime import datetime

# 1. Carregar a base que veio da etapa do Open-Meteo
print("[+] Carregando a base geoclimática...")
df = pd.read_csv('GSAF_clima.csv')

# Mapa para traduzir o texto do mês para número inteiro
MESES_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'september': 9
}

def calcular_dados_lunares(ano, mes, dia):
    try:
        # 1. Tratamento do Dia
        d_str = str(dia).strip().lower()
        if 'unknown' in d_str or not d_str.isdigit():
            d_int = 15 # Dia médio se desconhecido
        else:
            d_int = int(float(d_str))

        # 2. Tratamento do Mês
        m_str = str(mes).strip().lower()
        if m_str.isdigit():
            m_int = int(float(m_str))
        else:
            # Pega as 3 primeiras letras (ex: 'sep' de 'september') e converte
            m_int = MESES_MAP.get(m_str[:3], 1) # Usa 1 (Jan) como fallback

        # 3. Tratamento do Ano
        a_int = int(float(str(ano).strip()))

        # Cria o objeto de data para o cálculo astronômico
        data_dt = datetime(a_int, m_int, d_int)
        data_ephem = ephem.Date(data_dt)

        # Calcula a fração iluminada
        fração_iluminação = ephem.Moon(data_ephem).moon_phase

        proxima_lua = ephem.next_new_moon(data_ephem)
        ultima_lua = ephem.previous_new_moon(data_ephem)
        idade_da_lua = (data_ephem - ultima_lua)

        # Categorização
        if idade_da_lua < 3.7: fase = 'New Moon'
        elif idade_da_lua < 11.1: fase = 'Waxing Crescent'
        elif idade_da_lua < 18.4: fase = 'Full Moon'
        else: fase = 'Waning Crescent'

        return pd.Series([fração_iluminação, fase])
    except Exception as e:
        return pd.Series([np.nan, 'Unknown'])

print("[+] Calculando frações de iluminação e fases lunares...")
# Aplica a função matemática linha por linha
df[['moon_illumination', 'moon_phase']] = df.apply(
    lambda row: calcular_dados_lunares(row['Year'], row['Month'], row['Day']), axis=1
)

# Salva o progresso
df.to_csv('GSAF_clima_lua.csv', index=False)
print("[+] Fase da lua adicionada com sucesso! Arquivo 'GSAF_clima_lua.csv' gerado.")
print("\nDistribuição das fases da lua encontradas nos cenários de ataque:")
print(df['moon_phase'].value_counts())