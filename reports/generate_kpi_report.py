"""
Gerador de Relatório KPI de Chamados Jira - Jan a Abr 2026
Saída: HTML com Chart.js (sem dependências C/DLL)
"""
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from jinja2 import Template
from jira.client import JiraClient

# ── Configuração ──────────────────────────────────────────────────────────────
JQL = (
    'project = JDMSN1 '
    'AND status IN ("Aguardando retorno - Avalara", "Aguardando Retorno – Cliente", '
    '"Analise JDMS", "Concluído", "Pendente Analise", "Reabertura") '
    'AND created >= "2026-01-01" '
    'AND created <= "2026-04-28" '
    'AND reporter != "douglas.souza@jdmsconsulting.com.br" '
    'ORDER BY created ASC'
)
AVALARA_FIELD   = "customfield_10069"
PRODUCT_FIELD   = "customfield_10238"   # cascading: produto + subtipo
PRODUCT_FIELD2  = "customfield_10070"   # fallback produto simples
ORG_FIELD       = "customfield_10002"   # organização/empresa
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MESES = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril"}
ENGENHARIA_POR_MES = {1: 17, 2: 20, 3: 13, 4: 16}
PALETTE = ["#1F4E79", "#2E75B6", "#5BA4CF", "#9DC3E6",
           "#ED7D31", "#FFC000", "#70AD47", "#7030A0",
           "#FF0000", "#00B0F0", "#92D050", "#FF7C80"]


# ── Coleta ────────────────────────────────────────────────────────────────────
def fetch_issues() -> list[dict]:
    client = JiraClient()
    print("Buscando chamados no Jira...")
    issues = client.search_issues(JQL, max_results=0)
    print(f"  → {len(issues)} chamados encontrados.")
    return issues


def build_dataframe(issues: list[dict]) -> pd.DataFrame:
    rows = []
    status_resolvidos = {"concluído", "concluido", "resolved", "done", "fechado"}
    for issue in issues:
        f = issue.get("fields", {})

        reporter = (f.get("reporter") or {}).get("displayName", "Desconhecido")
        assignee = (f.get("assignee") or {}).get("displayName", "Não atribuído")
        status = (f.get("status") or {}).get("name", "Desconhecido")
        resolvido = status.lower() in status_resolvidos

        created_dt  = pd.to_datetime(f.get("created"), utc=True, errors="coerce")
        concluded_dt = pd.to_datetime(f.get("statuscategorychangedate"), utc=True, errors="coerce")
        if resolvido and pd.isna(concluded_dt):
          concluded_dt = pd.to_datetime(f.get("updated"), utc=True, errors="coerce")

        # Tempo de atendimento: criação até o chamado entrar em concluído.
        atend_dias = None
        if resolvido and pd.notna(created_dt) and pd.notna(concluded_dt):
          atend_dias = round((concluded_dt - created_dt).total_seconds() / 86400, 1)

        av_raw = f.get(AVALARA_FIELD)
        if isinstance(av_raw, dict):
            av_val = av_raw.get("value") or av_raw.get("name") or ""
        elif isinstance(av_raw, str):
            av_val = av_raw
        elif isinstance(av_raw, (int, float)):
            av_val = str(av_raw)  # número = ticket Avalara preenchido
        else:
            av_val = ""
        abriu_avalara = bool(av_val and av_val.strip() not in ("", "Não", "No", "Nao", "false", "False"))

        # Produto: tenta customfield_10238 (cascading) primeiro, depois fallback 10070
        prod_raw = f.get(PRODUCT_FIELD) or f.get(PRODUCT_FIELD2)
        if isinstance(prod_raw, dict):
            produto = prod_raw.get("value") or prod_raw.get("name") or "Não informado"
        elif isinstance(prod_raw, str):
            produto = prod_raw or "Não informado"
        else:
            produto = "Não informado"

        # Organização/empresa cliente
        org_raw = f.get(ORG_FIELD)
        if isinstance(org_raw, list) and org_raw:
            empresa = org_raw[0].get("name", reporter)
        else:
            empresa = reporter

        rows.append({
            "chave":            issue.get("key", ""),
            "cliente":          reporter,
            "empresa":          empresa,
            "consultor":        assignee,
            "status":           status,
            "produto":          produto,
            "criado_em":        created_dt,
          "resolvido_em":     concluded_dt,
            "mes":              int(created_dt.month) if pd.notna(created_dt) else None,
            "atendimento_dias": atend_dias,
            "abriu_avalara":    abriu_avalara,
          "resolvido":        resolvido,
        })

    return pd.DataFrame(rows)


# ── KPIs ──────────────────────────────────────────────────────────────────────
def calcular_kpis(df: pd.DataFrame) -> dict:
    total = len(df)
    resolvidos = int(df["resolvido"].sum())
    avalara = int(df["abriu_avalara"].sum())
    engenharia_total = sum(ENGENHARIA_POR_MES.values())

    resolved_df = df[df["resolvido"]]
    media_dias = resolved_df["atendimento_dias"].dropna().mean()
    media_dias_avalara = resolved_df[resolved_df["abriu_avalara"]]["atendimento_dias"].dropna().mean()
    media_dias_sem_avalara = resolved_df[~resolved_df["abriu_avalara"]]["atendimento_dias"].dropna().mean()

    return {
        "total": total,
        "resolvidos": resolvidos,
        "taxa_resolucao": f"{resolvidos/total*100:.1f}%" if total else "0%",
        "avalara_count": avalara,
        "avalara_pct": f"{avalara/total*100:.1f}%" if total else "0%",
        "engenharia_count": engenharia_total,
        "engenharia_pct_avalara": f"{engenharia_total/avalara*100:.1f}%" if avalara else "0%",
        "engenharia_pct_total": f"{engenharia_total/total*100:.1f}%" if total else "0%",
        "media_atendimento": f"{media_dias:.1f} dias" if pd.notna(media_dias) else "N/A",
        "media_avalara": f"{media_dias_avalara:.1f} dias" if pd.notna(media_dias_avalara) else "N/A",
        "media_sem_avalara": f"{media_dias_sem_avalara:.1f} dias" if pd.notna(media_dias_sem_avalara) else "N/A",
        "por_mes": {m: int(df[df["mes"] == m].shape[0]) for m in range(1, 5)},
    }


# ── Dados para gráficos Chart.js ──────────────────────────────────────────────
def dados_graficos(df: pd.DataFrame) -> dict:
    # Chamados por mês
    por_mes = [int(df[df["mes"] == m].shape[0]) for m in range(1, 5)]
    avalara_mes = [int(df[(df["mes"] == m) & df["abriu_avalara"]].shape[0]) for m in range(1, 5)]
    engenharia_mes = [ENGENHARIA_POR_MES.get(m, 0) for m in range(1, 5)]

    # Status
    st = df["status"].value_counts()
    status_labels = list(st.index)
    status_vals   = [int(v) for v in st.values]

    # Top 10 clientes (usa empresa se disponível)
    col_cli = "empresa" if "empresa" in df.columns else "cliente"
    top_cl = df[col_cli].value_counts().head(10)
    clientes_labels = list(top_cl.index)
    clientes_vals   = [int(v) for v in top_cl.values]

    # Produtos
    prod = df["produto"].value_counts().head(8)
    prod_labels = list(prod.index)
    prod_vals   = [int(v) for v in prod.values]

    return {
        "meses_labels":    list(MESES.values()),
        "por_mes":         por_mes,
        "avalara_mes":     avalara_mes,
        "engenharia_mes":  engenharia_mes,
        "status_labels":   status_labels,
        "status_vals":     status_vals,
        "clientes_labels": clientes_labels,
        "clientes_vals":   clientes_vals,

        "prod_labels":     prod_labels,
        "prod_vals":       prod_vals,
        "palette":         PALETTE,
    }


# ── Tabelas ───────────────────────────────────────────────────────────────────
def tabela_clientes(df: pd.DataFrame, top_n: int = 15) -> list[dict]:
    rows = []
    # Usa empresa se disponível, senão cliente
    col = "empresa" if "empresa" in df.columns else "cliente"
    for nome in df[col].value_counts().head(top_n).index:
        sub = df[df[col] == nome]
        total   = len(sub)
        avalara = int(sub["abriu_avalara"].sum())
        rows.append({"cliente": nome, "total": total, "avalara": avalara,
                     "pct": f"{avalara/total*100:.1f}%" if total else "0%"})
    return rows


def tabela_comparativo_mensal(df: pd.DataFrame) -> list[dict]:
    rows = []
    for m in range(1, 5):
        abertos = int(df[df["mes"] == m].shape[0])
        avalara = int(df[(df["mes"] == m) & df["abriu_avalara"]].shape[0])
        engenharia = int(ENGENHARIA_POR_MES.get(m, 0))
        rows.append({
            "mes": MESES[m],
            "abertos": abertos,
            "avalara": avalara,
            "engenharia": engenharia,
            "pct_avalara_para_eng": f"{engenharia/avalara*100:.1f}%" if avalara else "0%",
            "pct_aberto_para_eng": f"{engenharia/abertos*100:.1f}%" if abertos else "0%",
        })
    return rows



# ── Template HTML ─────────────────────────────────────────────────────────────
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Relatório KPI Suporte N1 — 2026 · JDMS Consulting</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
  --navy:   #0D2137;
  --blue:   #1A56A0;
  --blue2:  #2E75B6;
  --sky:    #5BA4CF;
  --green:  #059669;
  --orange: #D97706;
  --red:    #DC2626;
  --purple: #7C3AED;
  --teal:   #0891B2;
  --bg:     #F1F5F9;
  --card:   #FFFFFF;
  --border: #E2E8F0;
  --text:   #1E293B;
  --muted:  #64748B;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  line-height: 1.5;
}

/* ── HEADER ── */
.header {
  background: var(--navy);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 40px;
  height: 64px;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 12px rgba(0,0,0,.3);
}
.header-logo { font-size: 15px; font-weight: 700; letter-spacing: .5px; }
.header-logo span { color: var(--sky); }
.header-meta { font-size: 11px; color: rgba(255,255,255,.55); }

/* ── HERO ── */
.hero {
  background: linear-gradient(120deg, var(--navy) 0%, var(--blue) 55%, var(--blue2) 100%);
  color: #fff;
  padding: 48px 40px 40px;
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: '';
  position: absolute;
  right: -80px; top: -80px;
  width: 380px; height: 380px;
  border-radius: 50%;
  background: rgba(255,255,255,.04);
}
.hero-tag {
  display: inline-block;
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(255,255,255,.2);
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: .5px;
  text-transform: uppercase;
  margin-bottom: 14px;
}
.hero h1 { font-size: 28px; font-weight: 700; line-height: 1.2; }
.hero p  { font-size: 13px; color: rgba(255,255,255,.65); margin-top: 8px; }
.hero-date { font-size: 11px; color: rgba(255,255,255,.45); margin-top: 16px; }

/* ── LAYOUT ── */
.page { max-width: 1280px; margin: 0 auto; padding: 32px 40px 48px; }

/* ── SECTION HEADER ── */
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  margin-top: 40px;
}
.section-header h2 {
  font-size: 16px;
  font-weight: 700;
  color: var(--navy);
}
.section-header::before {
  content: '';
  display: block;
  width: 4px; height: 20px;
  background: var(--blue2);
  border-radius: 2px;
}
.section-tag {
  margin-left: auto;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--muted);
  background: var(--border);
  padding: 2px 8px;
  border-radius: 10px;
}

/* ── KPI CARDS ── */
.kpi-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.kpi-row.wide { grid-template-columns: repeat(6, 1fr); }

.kcard {
  background: var(--card);
  border-radius: 14px;
  padding: 22px 18px 18px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.05);
  border-top: 3px solid var(--blue2);
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: box-shadow .2s;
}
.kcard:hover { box-shadow: 0 4px 24px rgba(0,0,0,.12); }
.kcard.c-blue   { border-top-color: var(--blue2); }
.kcard.c-orange { border-top-color: var(--orange); }
.kcard.c-green  { border-top-color: var(--green); }
.kcard.c-purple { border-top-color: var(--purple); }
.kcard.c-teal   { border-top-color: var(--teal); }
.kcard.c-red    { border-top-color: var(--red); }

.kcard-icon { font-size: 20px; margin-bottom: 6px; }
.kcard-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
  color: var(--navy);
}
.kcard.c-orange .kcard-value { color: var(--orange); }
.kcard.c-green  .kcard-value { color: var(--green);  }
.kcard.c-purple .kcard-value { color: var(--purple); }
.kcard.c-teal   .kcard-value { color: var(--teal);   }
.kcard.c-red    .kcard-value { color: var(--red);    }
.kcard-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-top: 6px;
}
.kcard-sub {
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}
.kcard-badge {
  display: inline-block;
  margin-top: 8px;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 10px;
  background: #EFF6FF;
  color: var(--blue2);
}
.kcard.c-orange .kcard-badge { background:#FFF7ED; color:var(--orange); }
.kcard.c-green  .kcard-badge { background:#ECFDF5; color:var(--green);  }
.kcard.c-purple .kcard-badge { background:#F5F3FF; color:var(--purple); }
.kcard.c-teal   .kcard-badge { background:#ECFEFF; color:var(--teal);   }
.kcard.c-red    .kcard-badge { background:#FEF2F2; color:var(--red);    }

/* ── MONTH BAND ── */
.month-band {
  display: grid;
  grid-template-columns: repeat(4,1fr);
  gap: 12px;
  margin-top: 16px;
}
.mcard {
  background: var(--card);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06);
  display: flex;
  align-items: center;
  gap: 14px;
}
.mcard-circle {
  width: 52px; height: 52px;
  border-radius: 50%;
  background: #EFF6FF;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; font-weight: 700; color: var(--blue2);
  flex-shrink: 0;
}
.mcard-info { flex: 1; }
.mcard-name { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .4px; color: var(--muted); }
.mcard-val  { font-size: 24px; font-weight: 700; color: var(--navy); }
.mcard-sub  { font-size: 10px; color: var(--muted); }

/* ── CHART GRID ── */
.chart-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }
.ccart {
  background: var(--card);
  border-radius: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.05);
  padding: 22px 20px 18px;
}
.ccart.full { grid-column: span 2; }
.ccart-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--navy);
  text-transform: uppercase;
  letter-spacing: .4px;
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
canvas { max-height: 280px; }

/* ── TABLES ── */
.table-wrap { overflow-x: auto; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: var(--card);
}
thead { background: var(--navy); color: #fff; }
th {
  padding: 11px 16px;
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: .3px;
  text-transform: uppercase;
}
td { padding: 10px 16px; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
tr:nth-child(even) td { background: #F8FAFC; }
tr:hover td { background: #EFF6FF; transition: background .15s; }
.td-num  { font-weight: 600; color: var(--blue2); }
.td-high { font-weight: 700; color: var(--orange); }

/* ── DIVIDER ── */
.divider { border: none; border-top: 1px solid var(--border); margin: 32px 0; }

/* ── FOOTER ── */
.footer {
  background: var(--navy);
  color: rgba(255,255,255,.5);
  text-align: center;
  padding: 18px 40px;
  font-size: 11px;
  margin-top: 40px;
}
.footer strong { color: rgba(255,255,255,.8); }
</style>
</head>
<body>

<!-- HEADER -->
<header class="header">
  <div class="header-logo">JDMS <span>Consulting</span></div>
  <div class="header-meta">Relatório Suporte N1 · Gerado em {{ gerado_em }}</div>
</header>

<!-- HERO -->
<div class="hero">
  <div class="hero-tag">Relatório Executivo</div>
  <h1>Performance de Suporte N1</h1>
  <p>Janeiro a Abril de 2026 · Projeto JDMSN1 · JDMS Consulting</p>
  <div class="hero-date">Período: 01/01/2026 – 28/04/2026 · Total analisado: {{ kpis.total }} chamados</div>
</div>

<div class="page">

  <!-- ── KPIs PRINCIPAIS ── -->
  <div class="section-header">
    <h2>Indicadores Gerais</h2>
    <span class="section-tag">Jan – Abr 2026</span>
  </div>

  <div class="kpi-row wide">
    <div class="kcard c-blue">
      <div class="kcard-icon">📋</div>
      <div class="kcard-value">{{ kpis.total }}</div>
      <div class="kcard-label">Total de Chamados</div>
      <div class="kcard-sub">Jan – Abr 2026</div>
    </div>
    <div class="kcard c-green">
      <div class="kcard-icon">✅</div>
      <div class="kcard-value">{{ kpis.resolvidos }}</div>
      <div class="kcard-label">Chamados Resolvidos</div>
      <div class="kcard-sub">Taxa de resolução</div>
      <span class="kcard-badge">{{ kpis.taxa_resolucao }}</span>
    </div>
    <div class="kcard c-orange">
      <div class="kcard-icon">🔗</div>
      <div class="kcard-value">{{ kpis.avalara_count }}</div>
      <div class="kcard-label">Escalados à Avalara</div>
      <div class="kcard-sub">do total de chamados</div>
      <span class="kcard-badge">{{ kpis.avalara_pct }}</span>
    </div>
    <div class="kcard c-red">
      <div class="kcard-icon">⚙️</div>
      <div class="kcard-value">{{ kpis.engenharia_count }}</div>
      <div class="kcard-label">Para Engenharia</div>
      <div class="kcard-sub">{{ kpis.engenharia_pct_total }} do total</div>
      <span class="kcard-badge">{{ kpis.engenharia_pct_avalara }} dos Avalara</span>
    </div>
    <div class="kcard c-teal">
      <div class="kcard-icon">⏱️</div>
      <div class="kcard-value">{{ kpis.media_sem_avalara }}</div>
      <div class="kcard-label">Tempo Médio sem Avalara</div>
      <div class="kcard-sub">Chamados resolvidos internamente</div>
    </div>
    <div class="kcard c-purple">
      <div class="kcard-icon">⏳</div>
      <div class="kcard-value">{{ kpis.media_avalara }}</div>
      <div class="kcard-label">Tempo Médio com Avalara</div>
      <div class="kcard-sub">Chamados com suporte Avalara</div>
    </div>
  </div>

  <!-- ── CHAMADOS POR MÊS ── -->
  <div class="section-header" style="margin-top:32px;">
    <h2>Distribuição Mensal</h2>
  </div>
  <div class="month-band">
    {% for row in tabela_comparativo_mensal %}
    <div class="mcard">
      <div class="mcard-circle">{{ row.abertos }}</div>
      <div class="mcard-info">
        <div class="mcard-name">{{ row.mes }}</div>
        <div class="mcard-val">{{ row.abertos }}</div>
        <div class="mcard-sub">Avalara: {{ row.avalara }} · Eng: {{ row.engenharia }}</div>
      </div>
    </div>
    {% endfor %}
  </div>

  <!-- ── GRÁFICOS ── -->
  <div class="section-header">
    <h2>Análise Visual</h2>
  </div>
  <div class="chart-grid">

    <div class="ccart full">
      <div class="ccart-title">Comparativo Mensal — Abertos vs Escalados Avalara vs Encaminhados Engenharia</div>
      <canvas id="cAvalara"></canvas>
    </div>

    <div class="ccart">
      <div class="ccart-title">Chamados por Mês</div>
      <canvas id="cMes"></canvas>
    </div>

    <div class="ccart">
      <div class="ccart-title">Distribuição por Status</div>
      <canvas id="cStatus"></canvas>
    </div>

    <div class="ccart full">
      <div class="ccart-title">Top 10 Clientes com Maior Volume de Chamados</div>
      <canvas id="cClientes"></canvas>
    </div>

    <div class="ccart full">
      <div class="ccart-title">Chamados por Produto / Solução</div>
      <canvas id="cProduto"></canvas>
    </div>

  </div>

  <!-- ── TABELA COMPARATIVO ── -->
  <div class="section-header">
    <h2>Comparativo Mensal Detalhado</h2>
    <span class="section-tag">Abertos · Avalara · Engenharia</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Mês</th>
          <th>Chamados Abertos</th>
          <th>Com Chamado Avalara</th>
          <th>% Avalara</th>
          <th>Para Engenharia</th>
          <th>% Avalara → Eng.</th>
          <th>% Abertos → Eng.</th>
        </tr>
      </thead>
      <tbody>
        {% for row in tabela_comparativo_mensal %}
        <tr>
          <td><strong>{{ row.mes }}</strong></td>
          <td class="td-num">{{ row.abertos }}</td>
          <td class="td-num">{{ row.avalara }}</td>
          <td>{% if row.abertos %}{{ "%.1f"|format(row.avalara / row.abertos * 100) }}%{% else %}0%{% endif %}</td>
          <td class="td-high">{{ row.engenharia }}</td>
          <td>{{ row.pct_avalara_para_eng }}</td>
          <td>{{ row.pct_aberto_para_eng }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- ── TABELA CLIENTES ── -->
  <div class="section-header">
    <h2>Clientes com Maior Volume</h2>
    <span class="section-tag">Top 15</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Cliente</th>
          <th>Chamados</th>
          <th>Escalados à Avalara</th>
          <th>% Escalados</th>
        </tr>
      </thead>
      <tbody>
        {% for row in tabela_clientes %}
        <tr>
          <td style="color:var(--muted);font-weight:600">{{ loop.index }}</td>
          <td><strong>{{ row.cliente }}</strong></td>
          <td class="td-num">{{ row.total }}</td>
          <td class="td-num">{{ row.avalara }}</td>
          <td>{{ row.pct }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

</div><!-- /page -->

<footer class="footer">
  <strong>JDMS Consulting</strong> · Suporte N1 · Relatório gerado automaticamente em {{ gerado_em }} · Dados extraídos do Jira JDMSN1
</footer>

<script>
const P = {{ palette_json }};
const G = {{ graficos_json }};

const chartDefaults = {
  plugins: { legend: { labels: { font: { family: 'Inter', size: 11 }, usePointStyle: true } } },
  scales: {
    x: { grid: { color: '#F1F5F9' }, ticks: { font: { family: 'Inter', size: 11 } } },
    y: { grid: { color: '#F1F5F9' }, ticks: { font: { family: 'Inter', size: 11 } } }
  }
};

// Comparativo mensal (grouped bar – destaque principal)
new Chart(document.getElementById('cAvalara'), {
  type: 'bar',
  data: {
    labels: G.meses_labels,
    datasets: [
      { label: 'Chamados Abertos',         data: G.por_mes,          backgroundColor: '#2E75B6', borderRadius: 5 },
      { label: 'Escalados à Avalara',      data: G.avalara_mes,       backgroundColor: '#D97706', borderRadius: 5 },
      { label: 'Encaminhados Engenharia',  data: G.engenharia_mes,    backgroundColor: '#DC2626', borderRadius: 5 }
    ]
  },
  options: {
    ...chartDefaults,
    plugins: { ...chartDefaults.plugins, legend: { ...chartDefaults.plugins.legend, position: 'top' } },
    scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, beginAtZero: true } }
  }
});

// Chamados por mês (bar simples)
new Chart(document.getElementById('cMes'), {
  type: 'bar',
  data: {
    labels: G.meses_labels,
    datasets: [{ label: 'Chamados', data: G.por_mes, backgroundColor: ['#1A56A0','#2E75B6','#5BA4CF','#9DC3E6'], borderRadius: 6 }]
  },
  options: { ...chartDefaults, plugins: { legend: { display: false } } }
});

// Status (doughnut)
new Chart(document.getElementById('cStatus'), {
  type: 'doughnut',
  data: {
    labels: G.status_labels,
    datasets: [{ data: G.status_vals, backgroundColor: P, borderWidth: 2, borderColor: '#fff' }]
  },
  options: {
    plugins: { legend: { position: 'right', labels: { font: { family: 'Inter', size: 11 }, usePointStyle: true, padding: 14 } } },
    cutout: '60%'
  }
});

// Top clientes
new Chart(document.getElementById('cClientes'), {
  type: 'bar',
  data: {
    labels: G.clientes_labels,
    datasets: [{ label: 'Chamados', data: G.clientes_vals, backgroundColor: '#1A56A0', borderRadius: 4 }]
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: { x: { grid: { color: '#F1F5F9' }, ticks: { font: { family: 'Inter', size: 11 } } },
               y: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 11 } } } }
  }
});

// Produtos
new Chart(document.getElementById('cProduto'), {
  type: 'bar',
  data: {
    labels: G.prod_labels,
    datasets: [{ label: 'Chamados', data: G.prod_vals, backgroundColor: '#0891B2', borderRadius: 4 }]
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: { x: { grid: { color: '#F1F5F9' }, ticks: { font: { family: 'Inter', size: 11 } } },
               y: { grid: { display: false }, ticks: { font: { family: 'Inter', size: 11 } } } }
  }
});
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    issues = fetch_issues()
    if not issues:
        print("Nenhum chamado encontrado. Verifique JQL e credenciais.")
        return

    df = build_dataframe(issues)
    kpis = calcular_kpis(df)
    graf = dados_graficos(df)

    print(f"\n{'='*50}")
    print(f"  KPIs GERAIS")
    print(f"{'='*50}")
    print(f"  Total:                    {kpis['total']}")
    print(f"  Resolvidos:               {kpis['resolvidos']} ({kpis['taxa_resolucao']})")
    print(f"  Escalados à Avalara:      {kpis['avalara_count']} ({kpis['avalara_pct']})")
    print(f"  Para Engenharia:          {kpis['engenharia_count']} ({kpis['engenharia_pct_avalara']} dos Avalara)")
    print(f"  Tempo médio (Avalara):    {kpis['media_avalara']}")
    print(f"  Tempo médio (sem Avalara):{kpis['media_sem_avalara']}")
    print(f"  Jan:{kpis['por_mes'][1]} | Fev:{kpis['por_mes'][2]} | Mar:{kpis['por_mes'][3]} | Abr:{kpis['por_mes'][4]}")
    print(f"{'='*50}\n")

    print("Montando relatório HTML...")
    template = Template(HTML_TEMPLATE)
    html = template.render(
        kpis=kpis,
        gerado_em=datetime.now().strftime("%d/%m/%Y %H:%M"),
        graficos_json=json.dumps(graf, ensure_ascii=False),
        palette_json=json.dumps(PALETTE, ensure_ascii=False),
        tabela_comparativo_mensal=tabela_comparativo_mensal(df),
        tabela_clientes=tabela_clientes(df),
    )

    html_path = OUTPUT_DIR / "relatorio_kpi_jan_abr_2026.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  ✔ HTML salvo em: {html_path}")
    print("\nRelatório concluído! Abra o arquivo HTML no navegador para visualizar.")
    print(f"  Caminho: {html_path}")


if __name__ == "__main__":
    main()
