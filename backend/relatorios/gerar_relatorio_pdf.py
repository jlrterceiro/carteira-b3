import os
import sys
from datetime import date

from fpdf import FPDF

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from db_lib import get_conn


def fmt(v):
    if v is None:
        return '-'
    return f'{v:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def gerar(sg_usuario, nm_usuario, caminho_pdf):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sg_ticker, ganho_realizado_vendas, proventos, ganho_nao_realizado,
               ganho_total, valor_investido, ganho_pct_total
        FROM fn_ganho_total(NULL, NULL, NULL, NULL, %s)
        ORDER BY ganho_pct_total DESC
        """,
        (sg_usuario,),
    )
    linhas = cur.fetchall()

    cur.execute(
        """
        SELECT round(sum(ganho_realizado_vendas), 2), round(sum(proventos), 2),
               round(sum(ganho_nao_realizado), 2), round(sum(ganho_total), 2),
               round(sum(valor_investido), 2)
        FROM fn_ganho_total(NULL, NULL, NULL, NULL, %s)
        """,
        (sg_usuario,),
    )
    realizado, proventos, nao_realizado, total, investido = cur.fetchone()
    conn.close()

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 9, 'Relatorio de Ganhos - Carteira de Investimentos', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 7, f'{nm_usuario} ({sg_usuario})', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 6, f'Gerado em {date.today().strftime("%d/%m/%Y")}', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4)

    cols = ['Ativo', 'Realizado', 'Proventos', 'Nao realizado', 'Total', 'Investido', '% Total']
    widths = [28, 35, 35, 38, 35, 35, 30]

    def linha_tabela(valores, bold=False, fill=False):
        pdf.set_font('Helvetica', 'B' if bold else '', 10)
        if fill:
            pdf.set_fill_color(230, 230, 230)
        for w, v in zip(widths, valores):
            align = 'L' if v == valores[0] and not bold else 'R'
            if bold and v == valores[0]:
                align = 'L'
            pdf.cell(w, 7, str(v), border=1, align=align, fill=fill)
        pdf.ln()

    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(50, 50, 50)
    pdf.set_text_color(255, 255, 255)
    for w, c in zip(widths, cols):
        pdf.cell(w, 8, c, border=1, align='C', fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)

    for (ticker, real, prov, nao_real, tot, inv, pct) in linhas:
        fill = tot is not None and tot < 0
        valores = [
            ticker,
            fmt(real),
            fmt(prov),
            fmt(nao_real),
            fmt(tot),
            fmt(inv),
            f'{pct:.2f}%' if pct is not None else '-',
        ]
        if fill:
            pdf.set_fill_color(250, 235, 235)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.set_font('Helvetica', '', 9)
        for w, v in zip(widths, valores):
            align = 'L' if v == ticker else 'R'
            pdf.cell(w, 6.5, str(v), border=1, align=align, fill=True)
        pdf.ln()

    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(220, 220, 220)
    pct_total = round(100 * total / investido, 2) if investido else 0
    totais = ['TOTAL', fmt(realizado), fmt(proventos), fmt(nao_realizado), fmt(total), fmt(investido), f'{pct_total:.2f}%']
    for w, v in zip(widths, totais):
        align = 'L' if v == 'TOTAL' else 'R'
        pdf.cell(w, 7.5, str(v), border=1, align=align, fill=True)
    pdf.ln()

    pdf.output(caminho_pdf)
    print(f'PDF gerado: {caminho_pdf}')


if __name__ == '__main__':
    sg_usuario = sys.argv[1] if len(sys.argv) > 1 else 'ediesley'
    nm_usuario = sys.argv[2] if len(sys.argv) > 2 else sg_usuario
    caminho = sys.argv[3] if len(sys.argv) > 3 else f'relatorio_ganhos_{sg_usuario}.pdf'
    gerar(sg_usuario, nm_usuario, caminho)
