"""
RAIS (microdados de vínculos) -> estoque e saldo de emprego em 31/12
por município x atividade econômica, apenas PR, SC e RS, 1985-2025.

A atividade é harmonizada em SUBSETOR IBGE para a série inteira:
  - 1985-1993 e 2015 em diante: subsetor nativo (vem no arquivo);
  - 2006-2014: derivado da CNAE 2.0 (classe) por uma tabela de correspondência
    aprendida nos anos em que subsetor e CNAE 2.0 coexistem;
  - 1994-2005: derivado da CNAE 95 (classe) por correspondência aprendida
    nos anos em que subsetor (nativo ou derivado) e CNAE 95 coexistem.

Comandos
  download  : baixa os arquivos do FTP do PDET/MTE para data/raw/<ano>/
  inspect   : mostra cabeçalho e amostra de UM arquivo
  extract   : lê cada arquivo em chunks, filtra e agrega; um parquet por ano
  coverage  : % de vínculos com cada classificação de atividade, por ano
  crosswalk : constrói a correspondência CNAE -> subsetor e mostra a qualidade
  transicoes: compara os subsetores nos anos em que a origem da classificação muda
  build     : junta os anos e calcula estoque e saldo (total ou por atividade)
  painel    : exporta os painéis finais: com subsetor (ano, uf, mun, subsetor,
              estoque) e total por município (ano, uf, mun, estoque)

Dependências: pip install pandas pyarrow py7zr

Exemplos
  python rais_pipeline.py download --years 2015 --match SC --list
  python rais_pipeline.py inspect  --file data/raw/2023/RAIS_VINC_PUB_SUL.7z
  python rais_pipeline.py extract  --years 1994-2025
  python rais_pipeline.py coverage
  python rais_pipeline.py crosswalk
  python rais_pipeline.py build    --nivel total
  python rais_pipeline.py build    --nivel subsetor
  python rais_pipeline.py painel
  python rais_pipeline.py painel --nivel subsetor --ano-inicial 1995
"""

# ======================================================================
# 1. IMPORTAÇÕES
# ======================================================================
import argparse      # leitura dos comandos digitados no terminal
import ftplib        # conexão com o servidor FTP do ministério
import re            # expressões regulares (normalizar nomes)
import shutil        # apagar pastas temporárias
import tempfile      # pastas temporárias para descompactar
import unicodedata   # remover acentos dos nomes de colunas
import zipfile       # abrir arquivos .zip
from pathlib import Path

import pandas as pd  # manipulação das tabelas
import py7zr         # abrir arquivos .7z

# ======================================================================
# 2. CONFIGURAÇÕES
# ======================================================================
FTP_HOST = "ftp.mtps.gov.br"
FTP_BASE = "/pdet/microdados/RAIS"
FTP_PORT = 21

RAW = Path("data/raw")          # arquivos baixados
OUT = Path("data/processed")    # resultados

# Prefixos de UF no código de município (PR=41, SC=42, RS=43).
KEEP_UF_PREFIX = ("41", "42", "43")
UF_POR_PREFIXO = {"41": "PR", "42": "SC", "43": "RS"}  # sigla da UF

# Mapa de colunas: nome usado no código -> nomes possíveis no cabeçalho
# (já normalizados por norm()). Os layouts mudam entre anos; o layout de
# 2023 em diante usa o sufixo "_codigo".
REQUIRED = {
    "mun": ["municipio", "municipio_codigo", "mun_trab", "municipio_trab"],
    "ativo": ["vinculo_ativo_31_12", "ind_vinculo_ativo_31_12_codigo",
              "vinculo_ativo_31_12_codigo"],
}
OPTIONAL = {  # existem só em parte dos anos
    "subsetor": ["ibge_subsetor", "subsetor_ibge", "ibge_subsetor_codigo"],
    "cnae95": ["cnae_95_classe", "cnae_95_classe_codigo"],
    "cnae20": ["cnae_2_0_classe", "cnae_2_0_classe_codigo"],
}

# Pureza mínima (0 a 1) para aceitar uma correspondência de reserva por
# grupo (3 dígitos) ou divisão (2 dígitos) da CNAE 95, usada quando a
# classe (5 dígitos) não tem correspondência. 0.90 = pelo menos 90% dos
# vínculos do grupo/divisão caem no mesmo subsetor.
MIN_PUREZA = 0.90


# ======================================================================
# 3. FUNÇÕES AUXILIARES
# ======================================================================
def norm(s: str) -> str:
    """Normaliza nome de coluna: sem acento, minúsculas, símbolos -> "_".
    Ex.: 'Vínculo Ativo 31/12' -> 'vinculo_ativo_31_12'."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_years(spec: str):
    """'2010-2015' -> [2010..2015]; '2015' -> [2015]."""
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


# ======================================================================
# 4. ETAPA DOWNLOAD
# ======================================================================
def conectar():
    """Abre uma conexão FTP anônima nova (listagem em latin-1, porque há
    nomes de arquivo fora do UTF-8 no servidor)."""
    ftp = ftplib.FTP()
    ftp.encoding = "latin-1"
    ftp.connect(FTP_HOST, FTP_PORT, timeout=120)
    ftp.login()
    return ftp


def listar_ano(year, tokens):
    """Lista os arquivos de vínculos de um ano (None se a pasta não existe).
    Usa conexão própria, para não depender de uma conexão parada durante
    downloads longos."""
    with conectar() as ftp:
        try:
            ftp.cwd(f"{FTP_BASE}/{year}")
        except ftplib.error_perm:
            return None
        names = [n for n in ftp.nlst() if n.lower().endswith((".7z", ".zip"))]
    names = [n for n in names if "ESTAB" not in n.upper() and "ESTB" not in n.upper()]
    if tokens:
        names = [n for n in names if any(t in n.upper() for t in tokens)]
    return names


def baixar_arquivo(year, name, arquivo, tentativas=5):
    """Baixa um arquivo com retomada e novas tentativas.
    - Baixa para .part e só renomeia ao terminar.
    - Se a conexão cair, reconecta e retoma do ponto em que parou (REST).
    - Confere o tamanho final com o informado pelo servidor."""
    parcial = arquivo.with_name(arquivo.name + ".part")
    for tentativa in range(1, tentativas + 1):
        offset = parcial.stat().st_size if parcial.exists() else 0
        try:
            with conectar() as ftp:
                ftp.cwd(f"{FTP_BASE}/{year}")
                ftp.voidcmd("TYPE I")  # modo binário
                try:
                    esperado = ftp.size(name)
                except ftplib.error_perm:
                    esperado = None

                if esperado is not None and offset > esperado:
                    offset = 0  # .part maior que o original: recomeça
                if esperado is not None and offset == esperado:
                    parcial.replace(arquivo)  # já estava completo
                    return True

                with open(parcial, "ab" if offset else "wb") as fh:
                    proximo = [(fh.tell() // 100_000_000 + 1) * 100_000_000]

                    def escrever(bloco):
                        fh.write(bloco)
                        pos = fh.tell()
                        if pos >= proximo[0]:  # progresso a cada ~100 MB
                            total = f" / {esperado / 1e6:.0f} MB" if esperado else ""
                            print(f"    {pos / 1e6:.0f} MB{total}", flush=True)
                            proximo[0] = (pos // 100_000_000 + 1) * 100_000_000

                    ftp.retrbinary(f"RETR {name}", escrever, rest=offset or None)

            tamanho = parcial.stat().st_size
            if esperado is not None and tamanho != esperado:
                raise IOError(f"tamanho {tamanho} diferente do esperado {esperado}")
            parcial.replace(arquivo)
            return True
        except ftplib.error_perm as e:
            print(f"  erro do servidor ({e}); recomeçando do zero "
                  f"[tentativa {tentativa}/{tentativas}]", flush=True)
            parcial.unlink(missing_ok=True)
        except (OSError, EOFError, ftplib.Error) as e:
            print(f"  conexão interrompida ({e!r}); tentando retomar "
                  f"[tentativa {tentativa}/{tentativas}]", flush=True)
    return False


def cmd_download(args):
    tokens = [t.strip().upper() for t in args.match.split(",") if t.strip()]
    for year in parse_years(args.years):
        names = listar_ano(year, tokens)
        if names is None:
            print(year, "pasta não encontrada")
            continue
        if args.list:  # só mostra os nomes, sem baixar
            print(year, names)
            continue
        dest = RAW / str(year)
        dest.mkdir(parents=True, exist_ok=True)
        for n in names:
            arquivo = dest / n
            if arquivo.exists():  # já baixado por completo
                continue
            print("baixando", year, n, flush=True)
            if not baixar_arquivo(year, n, arquivo):
                print("  FALHOU:", year, n, "- repetir o comando depois", flush=True)


# ======================================================================
# 5. LEITURA DOS ARQUIVOS
# ======================================================================
def extract_txt(archive: Path, tmp: Path) -> Path:
    """Descompacta (.7z ou .zip) em `tmp` e devolve o maior arquivo
    extraído (o .txt com os dados)."""
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        with py7zr.SevenZipFile(archive) as z:
            z.extractall(path=tmp)
    files = [p for p in Path(tmp).rglob("*") if p.is_file()]
    return max(files, key=lambda p: p.stat().st_size)


def detectar_leitura(txt: Path) -> dict:
    """Descobre o separador olhando a primeira linha (cabeçalho). Layouts
    antigos usam ';', mas o de 2023 em diante pode usar outro. Codificação
    latin-1; tudo lido como texto para preservar zeros à esquerda."""
    with open(txt, "r", encoding="latin-1") as f:
        linha = f.readline()
    sep = max([";", ",", "\t", "|"], key=linha.count)
    return dict(sep=sep, encoding="latin-1", dtype=str)


def resolve_columns(cols):
    """Descobre, no cabeçalho do arquivo, a coluna real de cada nome do
    código. Devolve {nome_no_código: nome_real_no_arquivo}."""
    normed = {norm(c): c for c in cols}
    found = {}
    for canon, options in REQUIRED.items():  # obrigatórias: falta = erro
        hit = next((o for o in options if o in normed), None)
        if hit is None:
            raise KeyError(
                f"Coluna obrigatória '{canon}' não encontrada. "
                f"Esperado: {options}. Disponíveis: {sorted(normed)}"
            )
        found[canon] = normed[hit]
    for canon, options in OPTIONAL.items():  # opcionais: entram se existirem
        hit = next((o for o in options if o in normed), None)
        if hit is not None:
            found[canon] = normed[hit]
    return found


# ======================================================================
# 6. ETAPA INSPECT
# ======================================================================
def cmd_inspect(args):
    # Descompacta numa pasta temporária (apagada ao final), mostra a
    # primeira linha crua, o separador detectado e os nomes das colunas.
    with tempfile.TemporaryDirectory() as t:
        txt = extract_txt(Path(args.file), Path(t))
        kw = detectar_leitura(txt)
        with open(txt, "r", encoding="latin-1") as f:
            print("primeira linha (crua):", repr(f.readline()[:400]))
        print("separador detectado:", repr(kw["sep"]))
        df = pd.read_csv(txt, nrows=5, **kw)
        print("colunas originais -> normalizadas")
        for c in df.columns:
            print(f"  {c!r:45} -> {norm(c)}")
        print(df.head())


# ======================================================================
# 7. ETAPA EXTRACT (filtragem e agregação)
# ======================================================================
def clean_code(s: pd.Series, width: int) -> pd.Series:
    """Mantém só códigos numéricos válidos, com zeros à esquerda até
    `width` dígitos. Textos como '{ñ class}', negativos e códigos só de
    zeros (não classificado) viram "" (vazio)."""
    s = s.fillna("").str.strip()
    ok = s.str.fullmatch(r"\d+") & (s.str.lstrip("0") != "")
    return s.str.zfill(width).where(ok, "")


def process_chunk(df: pd.DataFrame, cols: dict) -> pd.DataFrame:
    """Processa um pedaço do arquivo: filtra e conta vínculos."""
    df = df.rename(columns={v: k for k, v in cols.items()})

    # Filtro 1: só vínculos ativos em 31/12 (define o estoque).
    df = df[df["ativo"] == "1"].copy()

    # Filtro 2: só PR, SC e RS. Código com 6 dígitos; se vier com 7
    # (dígito verificador IBGE), descarta o último para manter a mesma
    # chave em todos os anos.
    df["mun"] = df["mun"].fillna("").str.strip().str.zfill(6).str[:6]
    df = df[df["mun"].str.startswith(KEEP_UF_PREFIX)]

    # Atividade: subsetor (2 dígitos) e CNAE em nível de CLASSE (5 dígitos).
    # A classe é necessária para construir a correspondência CNAE -> subsetor.
    # Se a coluna não existe neste ano, a chave fica vazia.
    df["subsetor"] = clean_code(df["subsetor"], 2) if "subsetor" in df else ""
    df["cnae95"] = clean_code(df["cnae95"], 5) if "cnae95" in df else ""
    df["cnae20"] = clean_code(df["cnae20"], 5) if "cnae20" in df else ""

    # Cada linha é um vínculo: contar = somar uma coluna de 1s.
    df["n"] = 1
    return df.groupby(["mun", "subsetor", "cnae95", "cnae20"], as_index=False)["n"].sum()


def cmd_extract(args):
    OUT.mkdir(parents=True, exist_ok=True)
    for year in parse_years(args.years):
        destino = OUT / f"rais_mun_{year}.parquet"
        # Opcional: pula anos já extraídos. Usar só se o ano foi extraído
        # com TODOS os arquivos e já no esquema atual (com CNAE em classe).
        if args.skip_existing and destino.exists():
            print(year, "já extraído, pulando", flush=True)
            continue

        parts = []  # resultados parciais (um por chunk de cada arquivo)
        for archive in sorted((RAW / str(year)).glob("*")):
            if archive.suffix.lower() not in (".7z", ".zip"):
                continue
            # Pasta temporária apagada ao final (mesmo com erro).
            tmp = Path(tempfile.mkdtemp())
            try:
                txt = extract_txt(archive, tmp)
                kw = detectar_leitura(txt)
                # Só o cabeçalho (nrows=0), para descobrir as colunas do ano.
                cols = resolve_columns(pd.read_csv(txt, nrows=0, **kw).columns)
                # Pedaços de 1 milhão de linhas, só com as colunas necessárias.
                for i, chunk in enumerate(pd.read_csv(
                    txt, usecols=list(cols.values()), chunksize=1_000_000, **kw,
                ), start=1):
                    parts.append(process_chunk(chunk, cols))
                    print(f"  {year} {archive.name}: ~{i} milhão(ões) de linhas lidas",
                          flush=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            print(year, archive.name, "ok")

        if not parts:
            print(year, "sem arquivos em", RAW / str(year))
            continue

        # Soma os pedaços (o mesmo município pode aparecer em vários).
        out = (
            pd.concat(parts)
            .groupby(["mun", "subsetor", "cnae95", "cnae20"], as_index=False)["n"]
            .sum()
            .rename(columns={"n": "estoque_3112"})
        )
        out.insert(0, "ano", year)
        out.to_parquet(destino, index=False)
        print(year, "gravado", destino, flush=True)


# ======================================================================
# 8. CARGA DOS PARQUETS E COVERAGE
# ======================================================================
def carregar_extraidos(exigir_classe=False):
    """Junta os parquets anuais. Parquets do esquema antigo (CNAE só em
    divisão) são aceitos quando não trazem CNAE (ex.: 1985-1993); se
    `exigir_classe` e houver CNAE só em divisão, pede para refazer o extract."""
    partes, antigos = [], []
    for f in sorted(OUT.glob("rais_mun_*.parquet")):
        d = pd.read_parquet(f)
        if "cnae95" not in d.columns:  # esquema antigo
            tem_cnae = any(
                (d[c] != "").any() for c in ("cnae95_div", "cnae20_div") if c in d.columns
            )
            if tem_cnae:
                antigos.append(int(d["ano"].iloc[0]))
            d = d.drop(columns=[c for c in ("cnae95_div", "cnae20_div") if c in d.columns])
            d["cnae95"] = ""
            d["cnae20"] = ""
        partes.append(d)
    if not partes:
        raise FileNotFoundError(f"Nenhum parquet em {OUT}. Rodar o extract.")
    if exigir_classe and antigos:
        raise RuntimeError(
            "Anos no esquema antigo (CNAE só em divisão): "
            f"{antigos}. Refazer: python rais_pipeline.py extract --years "
            f"{min(antigos)}-{max(antigos)}"
        )
    return pd.concat(partes, ignore_index=True)


def cmd_coverage(args):
    """Por ano: estoque total e % de vínculos com subsetor, CNAE 95 e
    CNAE 2.0 preenchidos (diagnóstico das classificações)."""
    df = carregar_extraidos()
    linhas = []
    for ano, d in df.groupby("ano"):
        tot = max(d["estoque_3112"].sum(), 1)

        def pct(col):
            return 100 * d.loc[d[col] != "", "estoque_3112"].sum() / tot

        linhas.append({
            "ano": int(ano),
            "estoque_total": int(d["estoque_3112"].sum()),
            "pct_subsetor": pct("subsetor"),
            "pct_cnae95": pct("cnae95"),
            "pct_cnae20": pct("cnae20"),
        })
    print(pd.DataFrame(linhas).round(1).to_string(index=False))


# ======================================================================
# 9. HARMONIZAÇÃO EM SUBSETOR IBGE
# ======================================================================
def modal_map(df, chave, destino):
    """Correspondência chave -> destino: para cada código `chave`, escolhe
    o `destino` com mais vínculos. Devolve também `n_classe` (vínculos da
    chave) e `pureza` (parcela do destino escolhido; 1.0 = sem ambiguidade)."""
    d = df[(df[chave] != "") & (df[destino] != "")]
    t = d.groupby([chave, destino], as_index=False)["estoque_3112"].sum()
    t["n_classe"] = t.groupby(chave)["estoque_3112"].transform("sum")
    t["pureza"] = t["estoque_3112"] / t["n_classe"]
    t = (t.rename(columns={"estoque_3112": "n"})
          .sort_values("n", ascending=False)
          .drop_duplicates(chave)       # fica o destino mais frequente
          .sort_values(chave)
          .reset_index(drop=True))
    return t


def harmonizar_subsetor(df):
    """Cria `subsetor_h` (subsetor IBGE para a série inteira) e `origem`
    (de onde veio o subsetor de cada linha).
    Devolve (df, cws, diag): `cws` é um dicionário com as tabelas de
    correspondência e `diag` o diagnóstico da origem por ano."""
    df = df.copy()
    df["subsetor_h"] = df["subsetor"]
    df["origem"] = ""
    df.loc[df["subsetor"] != "", "origem"] = "nativo"

    # Passo A: CNAE 2.0 (classe) -> subsetor, aprendido onde os dois
    # existem nativamente (anos recentes). Aplicado onde falta o subsetor
    # mas existe CNAE 2.0 (ex.: 2006-2014).
    cw20 = modal_map(df[df["origem"] == "nativo"], "cnae20", "subsetor")
    m20 = dict(zip(cw20["cnae20"], cw20["subsetor"]))
    falta = (df["subsetor_h"] == "") & (df["cnae20"] != "")
    df.loc[falta, "subsetor_h"] = df.loc[falta, "cnae20"].map(m20).fillna("")
    df.loc[falta & (df["subsetor_h"] != ""), "origem"] = "cnae20"

    # Passo B: CNAE 95 (classe) -> subsetor, aprendido com tudo que já tem
    # subsetor_h (nativo ou derivado). Aplicado onde ainda falta subsetor
    # mas existe CNAE 95 (ex.: 1994-2005).
    cw95 = modal_map(df, "cnae95", "subsetor_h")
    m95 = dict(zip(cw95["cnae95"], cw95["subsetor_h"]))
    falta = (df["subsetor_h"] == "") & (df["cnae95"] != "")
    df.loc[falta, "subsetor_h"] = df.loc[falta, "cnae95"].map(m95).fillna("")
    df.loc[falta & (df["subsetor_h"] != ""), "origem"] = "cnae95"

    # Passos C e D (reserva): classes CNAE 95 que não aparecem nos anos em
    # que o subsetor é conhecido (ex.: classes extintas) ficam sem
    # correspondência. Nesses casos usa-se o GRUPO (3 dígitos) e, depois, a
    # DIVISÃO (2 dígitos) da CNAE 95, mas só quando o grupo/divisão cai
    # quase sempre em um único subsetor (pureza >= MIN_PUREZA).
    df["cnae95_grupo"] = df["cnae95"].str[:3]
    df["cnae95_div"] = df["cnae95"].str[:2]
    cws = {"cnae20": cw20, "cnae95": cw95}
    for nome in ("cnae95_grupo", "cnae95_div"):
        cw = modal_map(df, nome, "subsetor_h")
        cw["usada"] = cw["pureza"] >= MIN_PUREZA
        m = dict(zip(cw.loc[cw["usada"], nome], cw.loc[cw["usada"], "subsetor_h"]))
        falta = (df["subsetor_h"] == "") & (df[nome] != "")
        df.loc[falta, "subsetor_h"] = df.loc[falta, nome].map(m).fillna("")
        df.loc[falta & (df["subsetor_h"] != ""), "origem"] = nome
        cws[nome] = cw

    # Diagnóstico por ano: % do estoque por origem do subsetor.
    d = df.assign(origem=df["origem"].replace("", "sem_subsetor"))
    diag = d.pivot_table(index="ano", columns="origem", values="estoque_3112",
                         aggfunc="sum", fill_value=0)
    tot = diag.sum(axis=1)
    diag = diag.div(tot, axis=0).mul(100).round(1)
    diag.insert(0, "estoque_total", tot.astype(int))
    return df, cws, diag


def cmd_crosswalk(args):
    """Constrói a correspondência CNAE -> subsetor e mostra sua qualidade."""
    df = carregar_extraidos(exigir_classe=True)
    df, cws, diag = harmonizar_subsetor(df)

    # Qualidade de cada correspondência (pureza ponderada por vínculos).
    for nome, cw in cws.items():
        if not len(cw):
            print(f"{nome} -> subsetor: sem dados para aprender a correspondência")
            continue
        pureza = 100 * cw["n"].sum() / cw["n_classe"].sum()
        usadas = (f"; aceitas (pureza >= {MIN_PUREZA:.0%}): "
                  f"{int(cw['usada'].sum())}/{len(cw)}") if "usada" in cw else ""
        print(f"{nome} -> subsetor: {len(cw)} chaves; pureza ponderada "
              f"{pureza:.1f}%{usadas}")

    print("\nOrigem do subsetor por ano (% do estoque):")
    print(diag.to_string())

    # Combinações que continuam sem subsetor, com o período em que aparecem.
    sem = df[df["subsetor_h"] == ""]
    if len(sem):
        top = (sem.groupby(["cnae95", "cnae20"], as_index=False)
                  .agg(estoque_3112=("estoque_3112", "sum"),
                       ano_min=("ano", "min"), ano_max=("ano", "max"))
                  .sort_values("estoque_3112", ascending=False).head(10))
        print("\nCombinações CNAE ainda sem subsetor (10 maiores):")
        print(top.to_string(index=False))

    # Grava as correspondências para conferência (abre bem no Excel).
    OUT.mkdir(parents=True, exist_ok=True)
    for nome, cw in cws.items():
        cw.to_csv(OUT / f"crosswalk_{nome}_subsetor.csv", sep=";",
                  index=False, encoding="utf-8-sig")
    diag.to_csv(OUT / "diagnostico_origem_subsetor.csv", sep=";", encoding="utf-8-sig")
    print("\ngravado em", OUT)


def cmd_transicoes(args):
    """Compara o subsetor nos anos em que a ORIGEM da classificação muda
    (1994, 2006 e 2015): estoque, variação anual e participação de cada
    subsetor. Saltos fora do padrão sugerem reclassificação, não emprego."""
    df = carregar_extraidos(exigir_classe=True)
    df, _, _ = harmonizar_subsetor(df)
    df["subsetor_h"] = df["subsetor_h"].replace("", "00")
    s = df.groupby(["ano", "subsetor_h"])["estoque_3112"].sum().unstack(fill_value=0)
    part = s.div(s.sum(axis=1), axis=0) * 100
    var = s.pct_change() * 100
    for t in (1994, 2006, 2015):
        if t - 1 not in s.index or t not in s.index:
            continue
        tab = pd.DataFrame({
            "estoque_t-1": s.loc[t - 1],
            "estoque_t": s.loc[t],
            f"var_{t - 1}_%": var.loc[t - 1] if (t - 1) in var.index else float("nan"),
            f"var_{t}_%": var.loc[t],
            f"var_{t + 1}_%": var.loc[t + 1] if (t + 1) in var.index else float("nan"),
            "part_t-1_%": part.loc[t - 1],
            "part_t_%": part.loc[t],
            "dif_pp": part.loc[t] - part.loc[t - 1],
        }).round(1)
        print(f"\nTransição {t - 1} -> {t} (subsetor_h):")
        print(tab.to_string())


# ======================================================================
# 10. ETAPA BUILD (painel de estoque e saldo)
# ======================================================================
def calcular_painel(nivel, verbose=True):
    """Calcula o painel de estoque e saldo no nível pedido ("total",
    "subsetor", "cnae95" ou "cnae20"). Devolve (painel, chaves)."""
    if nivel == "total":
        # Total de empregos (todas as atividades): independe de classificação.
        df = carregar_extraidos()
        chaves = ["mun"]
    elif nivel == "subsetor":
        # Subsetor IBGE harmonizado na série inteira. Vínculos sem subsetor
        # identificável ficam na categoria "00", para que a soma dos
        # subsetores feche com o total.
        df = carregar_extraidos(exigir_classe=True)
        df, _, diag = harmonizar_subsetor(df)
        df["subsetor_h"] = df["subsetor_h"].replace("", "00")
        if verbose:
            print("Origem do subsetor por ano (% do estoque):")
            print(diag.to_string())
        # Marca os anos em que a origem predominante do subsetor muda
        # (ex.: 1994, 2006, 2015): nesses anos a classificação pode ter uma
        # quebra, e o saldo pode refletir reclassificação.
        origens = diag.drop(columns="estoque_total")
        dominante = origens.idxmax(axis=1)
        quebras = (dominante != dominante.shift(1)) & dominante.shift(1).notna()
        chaves = ["mun", "subsetor_h"]
    else:
        # CNAE por divisão (2 primeiros dígitos da classe), só nos anos
        # em que a classificação existe.
        df = carregar_extraidos(exigir_classe=True)
        col = {"cnae95": "cnae95", "cnae20": "cnae20"}[nivel]
        df = df[df[col] != ""].copy()
        df[col + "_div"] = df[col].str[:2]
        chaves = ["mun", col + "_div"]

    # Estoque em 31/12 por ano x chaves.
    est = df.groupby(["ano"] + chaves, as_index=False)["estoque_3112"].sum()

    # Painel completo: todas as combinações ano x município (x atividade);
    # combinações ausentes recebem estoque 0.
    grid = pd.MultiIndex.from_product(
        [sorted(est["ano"].unique())] + [sorted(est[k].unique()) for k in chaves],
        names=["ano"] + chaves,
    )
    est = (
        est.set_index(["ano"] + chaves)["estoque_3112"]
        .reindex(grid, fill_value=0)
        .reset_index()
        .sort_values(chaves + ["ano"])
    )

    # Saldo = estoque de 31/12 de t menos o de t-1, dentro de cada
    # município (x atividade). Se o ano anterior não existe na série, o
    # saldo fica vazio (evita misturar períodos de duração diferente).
    est["saldo"] = est.groupby(chaves)["estoque_3112"].diff()
    est.loc[est.groupby(chaves)["ano"].diff() != 1, "saldo"] = float("nan")

    if nivel == "subsetor":
        est["quebra_classificacao"] = (
            est["ano"].map(quebras.to_dict()).fillna(False).astype(bool)
        )
        anos_q = sorted(int(a) for a in est.loc[est["quebra_classificacao"], "ano"].unique())
        if verbose:
            print("anos com quebra de classificação (origem do subsetor muda):", anos_q)

    return est, chaves


def cmd_build(args):
    est, chaves = calcular_painel(args.nivel)
    dest = OUT / f"estoque_saldo_{args.nivel}.parquet"
    est.to_parquet(dest, index=False)
    print("gravado", dest, est.shape)
    print("municípios distintos:", est["mun"].nunique())
    if len(chaves) > 1:
        print(f"categorias de {chaves[1]}:", sorted(est[chaves[1]].unique()))


def exportar_painel(est, nome, com_subsetor, ano_inicial):
    """Grava um painel (parquet e CSV) em data/processed/painel_rais_mun_<nome>.
    Colunas: ano, uf, mun, [subsetor,] estoque. O painel é balanceado: toda
    combinação (município [x subsetor]) x ano aparece, com estoque 0 quando
    não há vínculos."""
    if ano_inicial:
        est = est[est["ano"] >= ano_inicial]

    painel = est.rename(columns={"subsetor_h": "subsetor", "estoque_3112": "estoque"})
    # Estado: o código do município começa com o código IBGE da UF.
    painel.insert(1, "uf", painel["mun"].str[:2].map(UF_POR_PREFIXO))
    chaves = ["mun"] + (["subsetor"] if com_subsetor else [])
    painel = (painel[["ano", "uf"] + chaves + ["estoque"]]
              .sort_values(chaves + ["ano"]).reset_index(drop=True))

    base = OUT / f"painel_rais_mun_{nome}"
    painel.to_parquet(base.with_suffix(".parquet"), index=False)
    # CSV com ';' e UTF-8 com BOM (abre no Excel). Atenção: o Excel remove
    # os zeros à esquerda de `mun` e `subsetor` ao abrir o CSV.
    painel.to_csv(base.with_suffix(".csv"), sep=";", index=False, encoding="utf-8-sig")

    print(f"\n[{nome}] gravado {base.with_suffix('.parquet')} e {base.with_suffix('.csv')}")
    print("  linhas:", len(painel), "| anos:", painel["ano"].min(), "a", painel["ano"].max())
    print("  municípios por UF:", painel.groupby("uf")["mun"].nunique().to_dict())
    if com_subsetor:
        print("  subsetores:", sorted(painel["subsetor"].unique()))
    print("  painel balanceado:", painel.groupby(chaves).size().nunique() == 1)
    return painel


def cmd_painel(args):
    """Exporta os painéis finais, cada um em UM arquivo:
      - subsetor: ano, uf, mun, subsetor, estoque (subsetor IBGE harmonizado);
      - total   : ano, uf, mun, estoque (todos os vínculos ativos em 31/12
                  somados, independe de classificação de atividade).
    Por padrão gera os dois; `--nivel` gera só um (útil para usar janelas
    de anos diferentes em cada painel)."""
    saidas = {}
    if args.nivel in ("subsetor", "ambos"):
        est, _ = calcular_painel("subsetor", verbose=False)
        saidas["subsetor"] = exportar_painel(est, "subsetor", True, args.ano_inicial)
    if args.nivel in ("total", "ambos"):
        est, _ = calcular_painel("total", verbose=False)
        saidas["total"] = exportar_painel(est, "total", False, args.ano_inicial)

    # Conferência: a soma dos subsetores deve fechar com o total, ano a ano.
    if len(saidas) == 2:
        a = saidas["subsetor"].groupby("ano")["estoque"].sum()
        b = saidas["total"].groupby("ano")["estoque"].sum()
        anos = a.index.intersection(b.index)
        ok = bool((a.loc[anos] == b.loc[anos]).all())
        print("\nsoma dos subsetores confere com o total em todos os anos:", ok)


# ======================================================================
# 11. INTERFACE DE LINHA DE COMANDO
# ======================================================================
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download")
    d.add_argument("--years", required=True)          # ex.: 2015 ou 2010-2015
    d.add_argument("--match", default="")             # ex.: SC,PR,RS ou SUL
    d.add_argument("--list", action="store_true")     # só listar
    d.set_defaults(fn=cmd_download)

    i = sub.add_parser("inspect")
    i.add_argument("--file", required=True)
    i.set_defaults(fn=cmd_inspect)

    e = sub.add_parser("extract")
    e.add_argument("--years", required=True)
    e.add_argument("--skip-existing", action="store_true")
    e.set_defaults(fn=cmd_extract)

    c = sub.add_parser("coverage")
    c.set_defaults(fn=cmd_coverage)

    w = sub.add_parser("crosswalk")
    w.set_defaults(fn=cmd_crosswalk)

    t = sub.add_parser("transicoes")
    t.set_defaults(fn=cmd_transicoes)

    pn = sub.add_parser("painel")
    pn.add_argument("--nivel", choices=["ambos", "subsetor", "total"], default="ambos")
    pn.add_argument("--ano-inicial", type=int, default=None)  # ex.: 1995
    pn.set_defaults(fn=cmd_painel)

    b = sub.add_parser("build")
    b.add_argument("--nivel", choices=["total", "subsetor", "cnae95", "cnae20"],
                   default="total")
    b.set_defaults(fn=cmd_build)

    a = p.parse_args()
    a.fn(a)
