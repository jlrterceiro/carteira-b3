import os
import sys
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from fpdf import FPDF

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from db_lib import get_conn

# Screening: ROE > 8% em pelo menos um dos ultimos 5 exercicios anuais, dividendo medio dos
# ultimos 5 anos (por acao) >= 5% sobre o preco atual, liquidez corrente > 1, NCAV positivo
# (patrimonio liquido > 0 e ativo circulante > passivo exigivel). Ordenado por Valor de
# Mercado / NCAV ascendente, mesma convencao do gerar_relatorio_ncav.py (menor = mais
# descontado).
QUERY = '''
WITH balanco_recente AS (
    SELECT DISTINCT ON (id_ativo)
        id_ativo, dt_referencia, vl_ativo_circulante, vl_passivo_total, vl_passivo_circulante,
        vl_patrimonio_liquido, vl_divida_total
    FROM tb_balanco_patrimonial
    WHERE tp_periodo = 'TRIMESTRAL'
    ORDER BY id_ativo, dt_referencia DESC
),
vm_recente AS (
    SELECT DISTINCT ON (id_ativo) id_ativo, vl_valor_mercado
    FROM tb_valor_mercado
    ORDER BY id_ativo, dt_referencia DESC
),
preco_recente AS (
    SELECT DISTINCT ON (id_ativo) id_ativo, vl_fechamento, dt_cotacao
    FROM tb_cotacao
    ORDER BY id_ativo, dt_cotacao DESC
),
roe_anual AS (
    SELECT d.id_ativo, d.dt_referencia, d.vl_lucro_liquido / b.vl_patrimonio_liquido AS roe
    FROM tb_dre d
    JOIN tb_balanco_patrimonial b
      ON b.id_ativo = d.id_ativo AND b.dt_referencia = d.dt_referencia AND b.tp_periodo = 'TRIMESTRAL'
    WHERE d.tp_periodo = 'ANUAL'
      AND d.vl_lucro_liquido IS NOT NULL AND b.vl_patrimonio_liquido > 0
),
roe_max_5anos AS (
    SELECT id_ativo, MAX(roe) AS roe_max
    FROM (
        SELECT id_ativo, dt_referencia, roe,
               ROW_NUMBER() OVER (PARTITION BY id_ativo ORDER BY dt_referencia DESC) AS rn
        FROM roe_anual
    ) x
    WHERE rn <= 5
    GROUP BY id_ativo
),
dividendos_5anos AS (
    SELECT id_ativo, SUM(vl_unitario_ajustado) / 5.0 AS dividendo_anual_medio
    FROM tb_provento
    WHERE dt_ex >= CURRENT_DATE - INTERVAL '5 years'
    GROUP BY id_ativo
)
SELECT
    a.sg_ticker,
    round((r.roe_max * 100)::numeric, 2) AS roe_max_pct,
    round(((dv.dividendo_anual_medio / p.vl_fechamento) * 100)::numeric, 2) AS dy_medio_pct,
    round((b.vl_ativo_circulante / b.vl_passivo_circulante)::numeric, 2) AS liquidez_corrente,
    round((b.vl_divida_total / b.vl_patrimonio_liquido)::numeric, 2) AS divida_pl,
    round((b.vl_ativo_circulante - b.vl_passivo_total)::numeric, 0) AS ncav,
    round(v.vl_valor_mercado::numeric, 0) AS valor_mercado,
    round((v.vl_valor_mercado / (b.vl_ativo_circulante - b.vl_passivo_total))::numeric, 4) AS vm_sobre_ncav,
    p.dt_cotacao
FROM balanco_recente b
JOIN tb_ativo a ON a.id_ativo = b.id_ativo
JOIN vm_recente v ON v.id_ativo = b.id_ativo
JOIN preco_recente p ON p.id_ativo = b.id_ativo
JOIN roe_max_5anos r ON r.id_ativo = b.id_ativo
JOIN dividendos_5anos dv ON dv.id_ativo = b.id_ativo
WHERE b.vl_patrimonio_liquido > 0
  AND b.vl_ativo_circulante > b.vl_passivo_total
  AND b.vl_passivo_circulante > 0
  AND r.roe_max > 0.08
  AND (dv.dividendo_anual_medio / p.vl_fechamento) >= 0.05
  AND (b.vl_ativo_circulante / b.vl_passivo_circulante) > 1
ORDER BY vm_sobre_ncav ASC
'''

COLS = [
    'Ticker', 'ROE max 5a (%)', 'DY medio 5a (%)', 'Liq. Corrente', 'Divida/PL',
    'NCAV', 'Valor Mercado', 'VM/NCAV', 'Cotacao em',
]


def fmt_num(v):
    if v is None:
        return '-'
    return f'{v:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def buscar_dados():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(QUERY)
    linhas = cur.fetchall()
    conn.close()
    return linhas


def gerar_pdf(linhas, caminho):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font('Helvetica', 'B', 15)
    pdf.cell(0, 9, 'Screening: ROE, dividendo, liquidez e desconto por NCAV', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(
        0, 6,
        'Filtro: ROE > 8% em algum dos ultimos 5 exercicios anuais, dividendo medio dos '
        'ultimos 5 anos >= 5% sobre o preco atual, liquidez corrente > 1, NCAV positivo.',
        new_x='LMARGIN', new_y='NEXT',
    )
    pdf.cell(0, 6, 'Ordenado por Valor de Mercado / NCAV (menor = mais descontado).', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 6, f'Gerado em {date.today().strftime("%d/%m/%Y")}', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)

    widths = [20, 24, 24, 22, 20, 30, 32, 20, 26]

    pdf.set_font('Helvetica', 'B', 8.5)
    pdf.set_fill_color(50, 50, 50)
    pdf.set_text_color(255, 255, 255)
    for w, c in zip(widths, COLS):
        pdf.cell(w, 8, c, border=1, align='C', fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)

    pdf.set_font('Helvetica', '', 8)
    for (ticker, roe, dy, liq, divpl, ncav, vm, ratio, dt_cot) in linhas:
        valores = [
            ticker,
            fmt_num(roe), fmt_num(dy), fmt_num(liq), fmt_num(divpl),
            fmt_num(ncav), fmt_num(vm), fmt_num(ratio),
            dt_cot.strftime('%d/%m/%Y'),
        ]
        for w, v in zip(widths, valores):
            align = 'L' if v == ticker else 'R'
            pdf.cell(w, 6.5, str(v), border=1, align=align)
        pdf.ln()

    pdf.output(caminho)
    print(f'PDF gerado: {caminho}')


def gerar_excel(linhas, caminho):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Screening'

    ws.append(COLS)
    header_fill = PatternFill(start_color='323232', end_color='323232', fill_type='solid')
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    for (ticker, roe, dy, liq, divpl, ncav, vm, ratio, dt_cot) in linhas:
        ws.append([ticker, roe, dy, liq, divpl, ncav, vm, ratio, dt_cot])

    for row in ws.iter_rows(min_row=2):
        for cell in row[1:5]:
            cell.number_format = '#,##0.00'
        for cell in row[5:7]:
            cell.number_format = '#,##0'
        row[7].number_format = '0.0000'
        row[8].number_format = 'DD/MM/YYYY'

    larguras = [10, 14, 14, 12, 10, 16, 16, 10, 12]
    for i, w in enumerate(larguras, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    wb.save(caminho)
    print(f'Excel gerado: {caminho}')


if __name__ == '__main__':
    linhas = buscar_dados()
    gerar_pdf(linhas, 'relatorio_screening.pdf')
    gerar_excel(linhas, 'relatorio_screening.xlsx')
