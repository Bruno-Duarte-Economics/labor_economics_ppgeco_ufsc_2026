# Estoque de emprego formal (RAIS) e controle sintético: Itapoá e Navegantes

Última atualização: 24/11/2026

## 1. Visão geral

Este projeto mede o efeito de Terminais de Uso Privativo (TUPs) sobre o **emprego formal** de municípios catarinenses, com controle sintético. O trabalho teve três etapas, rodadas com ferramentas diferentes:

| Etapa | O que faz | Como foi rodada |
|---|---|---|
| **A. Extração da RAIS** | Baixa os microdados de vínculos (1985–2025) e filtra PR, SC e RS | **Python, no terminal (PowerShell)**, com o script `rais_pipeline.py` e os comandos `download`, `inspect` e `extract` |
| **B. Organização dos dados** | Harmoniza a atividade em subsetor IBGE, constrói os painéis município × ano | **Python, no terminal (PowerShell)**, com o mesmo script: `coverage`, `crosswalk`, `transicoes`, `build` e `painel` |
| **C. Controle sintético (SCM)** | Estima o efeito sobre o estoque de emprego de Itapoá e Navegantes | **Notebook Jupyter** (`SCM.ipynb`), executado célula a célula, uma vez por município, com a biblioteca `pysyncon` |

Fluxo dos dados:

```
FTP do PDET/MTE (.7z)  ->  data/raw/<ano>/  ->  rais_mun_<ano>.parquet  ->  painel_rais_mun_total.parquet  ->  SCM.ipynb  ->  Excel, PNG e HTML
        download                 extract              (A)                    painel (B)                      (C)
```

O estoque de emprego usado no SCM é a soma de todos os vínculos formais ativos em 31/12, por município e ano. O painel por subsetor também foi construído, mas não entrou no SCM desta rodada.

## 2. Estrutura de pastas

```
Dissertacao/
├── 3. First Essay - TUPs impact/05. Python/
│   ├── .venv/                          ambiente virtual
│   ├── requirements.txt                lista de pacotes
│   ├── rais_pipeline.py                script da RAIS (linha de comando)
│   ├── SCM.ipynb                       notebook do controle sintético
│   ├── mun_ibge.xlsx                   tabela código IBGE (7 dígitos) e nome do município (SC)
│   ├── README_rais_pipeline.md         este arquivo
│   └── data/
│       ├── raw/<ano>/                  arquivos .7z baixados do FTP
│       └── processed/                  parquets, painéis finais e tabelas de correspondência
└── 7. Papers/1.TUPs impact/
    ├── 02. Dados/bd_BA_ES_SC.xlsx      banco original (usado só para o indicador IP)
    └── 04. Python/Resultados/Employment stock/<município>/    saídas do SCM
```

Os caminhos do script `rais_pipeline.py` são relativos à pasta de onde ele é executado, que deve ser `05. Python`. O notebook usa caminhos absolutos definidos na célula de parâmetros.

O `SCM.ipynb` está indicado na pasta `05. Python`; ajustar este desenho se ele estiver em outro local.

## 3. Ambiente

Pacotes (`requirements.txt`): `pandas`, `numpy`, `pyarrow`, `py7zr`, `pysyncon`, `matplotlib` e `openpyxl`. Para executar o notebook também é necessário o suporte a notebooks (`ipykernel`) no ambiente.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

- Se o `python` apontar para o Python da Microsoft Store (caminho com `WindowsApps`) em vez do `.venv`, usar o caminho completo: `.\.venv\Scripts\python.exe`.
- O botão de executar do VS Code roda o script sem argumentos e gera o erro `the following arguments are required: cmd`. O `rais_pipeline.py` precisa de um comando, digitado no terminal.

## 4. Etapa A: extração da RAIS (terminal)

### 4.1 Comandos do script

| Comando | O que faz | Deixa no disco |
|---|---|---|
| `download` | Baixa os `.7z` do FTP do PDET/MTE | `data/raw/<ano>/` |
| `inspect` | Mostra a primeira linha, o separador e as colunas de um arquivo | nada (só imprime) |
| `extract` | Filtra e conta vínculos por município, subsetor e CNAE (em **classe**, 5 dígitos) | `data/processed/rais_mun_<ano>.parquet` |
| `coverage` | Mostra, por ano, a % de vínculos com cada classificação de atividade | nada (só imprime) |
| `crosswalk` | Constrói a correspondência CNAE → subsetor e mostra sua qualidade e a origem do subsetor por ano | CSVs em `data/processed/` |
| `transicoes` | Compara os subsetores nos anos em que a origem da classificação muda (1994, 2006 e 2015) | nada (só imprime) |
| `build` | Junta os anos e calcula estoque e saldo | `data/processed/estoque_saldo_<nivel>.parquet` |
| `painel` | Exporta os dois painéis finais, cada um em um único arquivo | `data/processed/painel_rais_mun_subsetor.*` e `painel_rais_mun_total.*` (parquet e CSV) |

### 4.2 Ordem de execução (PowerShell)

```powershell
# 1. Conferir os arquivos disponíveis (não baixa nada)
python rais_pipeline.py download --years 1985-2017 --match PR,SC,RS --list
python rais_pipeline.py download --years 2018-2025 --match SUL --list

# 2. Baixar (se a conexão cair, repetir o mesmo comando)
python rais_pipeline.py download --years 1985-2017 --match PR,SC,RS
python rais_pipeline.py download --years 2018-2025 --match SUL

# 3. Conferir o layout de um arquivo
python rais_pipeline.py inspect --file "data\raw\2023\RAIS_VINC_PUB_SUL.7z"

# 4. Extrair (demorado; pode ser feito em blocos de anos)
python rais_pipeline.py extract --years 1994-2025

# 5. Diagnósticos
python rais_pipeline.py coverage
python rais_pipeline.py crosswalk
python rais_pipeline.py transicoes

# 6. Painéis
python rais_pipeline.py build --nivel total
python rais_pipeline.py build --nivel subsetor
python rais_pipeline.py painel
```

Níveis do `build`: `total` (padrão), `subsetor` (harmonizado), `cnae95` e `cnae20` (divisão, só nos anos em que existem). O `painel` aceita `--nivel` (`total`, `subsetor` ou `ambos`) e `--ano-inicial`, para dar janelas de anos diferentes a cada painel.

Observações:

- O `download` mostra o progresso a cada ~100 MB. Se for interrompido, repetir o mesmo comando retoma de onde parou.
- O `extract` imprime uma linha a cada 1 milhão de linhas lidas. De 1994 em diante é necessário o esquema atual (CNAE em classe); 1985–1993 só tem subsetor, e os parquets desses anos continuam válidos. `--skip-existing` pula anos já extraídos e só deve ser usado se o ano foi extraído com todos os arquivos e no esquema atual.
- Se o `crosswalk`, o `transicoes` ou o `build --nivel subsetor` encontrarem parquets no esquema antigo (CNAE só em divisão) a partir de 1994, o erro indica quais anos refazer.

### 4.3 Lógica

Os microdados são grandes (vários GB por ano). O trabalho é dividido em etapas, e cada uma grava o resultado em disco para a seguinte:

1. **Download**: arquivos compactados do FTP.
2. **Extração**: cada arquivo é descompactado em pasta temporária e lido em pedaços de 1 milhão de linhas (*chunks*), apenas com as colunas necessárias. Em cada pedaço, mantêm-se só os vínculos ativos em 31/12 de municípios do PR, SC e RS, e os vínculos são contados por município, subsetor, CNAE 95 (classe) e CNAE 2.0 (classe). O resultado agregado, muito menor que o original, é gravado em um parquet por ano.
3. **Harmonização, diagnóstico e painéis**: trabalham apenas sobre os parquets já agregados, por isso são rápidos e não voltam aos arquivos brutos.

**Parquet** é um formato colunar binário: gera arquivos menores que o CSV, lê rápido e preserva os tipos (códigos continuam texto, com zeros à esquerda). Leitura: `pd.read_parquet("caminho.parquet")`.

### 4.4 Leitura, filtros e download

- **Estoque em 31/12 (`Vínculo Ativo 31/12 == 1`)**: a RAIS é um registro anual, e o estoque de 31/12 é a medida padrão de emprego formal.
- **Filtro por prefixo do código do município** (PR = 41, SC = 42, RS = 43): o código da RAIS tem 6 dígitos, sem o dígito verificador do IBGE. Vale tanto para arquivos por UF quanto para os regionais (`SUL`). Se o código vier com 7 dígitos (layout novo), o último é descartado.
- **Coluna de município = `Município`**: é a única disponível em 1985. A partir de 2006 existe também `Mun Trab`, não utilizada.
- **Todas as colunas lidas como texto (`dtype=str`)**: preserva zeros à esquerda em códigos.
- **Limpeza de códigos de atividade**: os arquivos trazem `{ñ class}`, valores negativos e `00000` quando a classificação não se aplica. Esses valores viram vazio.
- **Separador detectado pela primeira linha**: o layout de 2023 em diante não segue o `;` dos anteriores.
- **Download em arquivo `.part`, com retomada**: o arquivo só é renomeado ao final. Se a conexão cair, o script reconecta e retoma do ponto em que parou (até 5 tentativas) e confere o tamanho final com o informado pelo servidor. Cada arquivo usa uma conexão própria, porque uma conexão parada durante um download longo é derrubada pelo servidor.
- **Listagem do FTP em `latin-1`**: há nomes de arquivo fora do UTF-8 (erro `UnicodeDecodeError` em 2024).

### 4.5 O que se sabe sobre os dados da RAIS

**Organização do FTP** (`ftp://ftp.mtps.gov.br/pdet/microdados/RAIS/<ano>/`):

- **1985 a 2017**: um arquivo por UF (`PR2015.7z`, `SC2015.7z`, `RS2015.7z`). Em anos antigos há também `IGNORADO*`/`IGNORANDOS*` (vínculos sem UF identificada), não utilizados.
- **2018 a 2025**: arquivos regionais (`RAIS_VINC_PUB_SUL.7z`, que reúne PR, SC e RS). Os arquivos `NI` e de outras regiões não são utilizados.
- Arquivos de estabelecimentos (`ESTB*`, `Estb2006.zip`) são ignorados.
- Os dicionários de layout ficam na página de Microdados RAIS e CAGED do PDET (gov.br/trabalho-e-emprego).

**Layout de 2023 em diante** (conferido com `inspect`): separador `,`, nomes de coluna entre aspas e no formato `Nome - Código` (por exemplo `Município - Código`, `Ind Vínculo Ativo 31/12 - Código`, `IBGE Subsetor - Código`, `CNAE 95 Classe - Código`, `CNAE 2.0 Classe - Código`); 62 colunas. O script detecta o separador pela primeira linha e aceita esses nomes. A extração de 2023, 2024 e 2025 funcionou, com as três classificações 100% preenchidas.

**Estoque de vínculos ativos em 31/12 (PR + SC + RS)**, em milhões: 3,45 (1985), 4,14 (1994), 5,83 (2005), 8,55 (2014), 8,09 (2016), 8,23 (2018), 8,27 (2020), 9,27 (2022), 9,58 (2023), 9,87 (2024), 10,16 (2025).

- Não há descontinuidade visível entre os arquivos por UF (até 2017) e os regionais (a partir de 2018): 8,14 milhões em 2017 e 8,23 milhões em 2018.
- A queda de 2014 para 2016 é compatível com a recessão do período. O crescimento de 2023 a 2025 (cerca de 3% ao ano) é compatível com os anos anteriores, o que não indica ano parcial em 2025.
- Os totais ainda não foram comparados com os números oficiais publicados por UF.

## 5. Etapa B: organização dos dados (terminal)

### 5.1 Harmonização da atividade em subsetor IBGE

Nenhuma classificação de atividade cobre a série inteira. Percentual dos vínculos ativos com a classificação preenchida (`coverage`):

| Período | Subsetor IBGE | CNAE 95 | CNAE 2.0 |
|---|---|---|---|
| 1985–1993 | 99,6% em 1985, caindo até 84,1% em 1993 | não existe | não existe |
| 1994–2005 | não existe | 96,0% em 1994, 99,4% em 1995, ~100% a partir de 1998 | não existe |
| 2006–2014 | não existe | 100% | 100% |
| 2015–2025 | 100% | 100% | 100% |

A escolha foi usar o **subsetor IBGE em todos os anos**, preenchido onde falta por correspondência com a CNAE:

- **Nativo** em 1985–1993 e de 2015 em diante.
- **Passo A, 2006–2014**: derivado da **CNAE 2.0 (classe)**, por uma correspondência aprendida nos anos em que subsetor e CNAE 2.0 coexistem nativamente (2015 em diante).
- **Passo B, 1994–2005**: derivado da **CNAE 95 (classe)**, por uma correspondência aprendida em todos os anos que já têm subsetor (nativo ou derivado no passo A) junto com CNAE 95.
- **Passos C e D (reserva)**: classes CNAE 95 sem correspondência usam a correspondência pelo **grupo** (3 dígitos) e, depois, pela **divisão** (2 dígitos), mas só quando o grupo ou a divisão cai num único subsetor em pelo menos 90% dos vínculos (`MIN_PUREZA` no início do script). A origem de cada linha fica registrada (`nativo`, `cnae20`, `cnae95`, `cnae95_grupo`, `cnae95_div`).
- **Correspondência modal e pureza**: cada classe CNAE recebe o subsetor com mais vínculos. A **pureza** mede a parcela dos vínculos da classe que cai no subsetor escolhido (100% = sem ambiguidade).
- **Por que classe e não divisão**: uma divisão CNAE pode se repartir entre mais de um subsetor. Por isso o `extract` guarda a CNAE em classe (5 dígitos).
- **Categoria `00`**: vínculos sem subsetor identificável ficam em `00` no painel por subsetor, para que a soma dos subsetores feche com o total.
- **Arquivos gravados** em `data/processed/`: `crosswalk_cnae20_subsetor.csv`, `crosswalk_cnae95_subsetor.csv`, `crosswalk_cnae95_grupo_subsetor.csv`, `crosswalk_cnae95_div_subsetor.csv` e `diagnostico_origem_subsetor.csv`.

**Qualidade da correspondência** (`crosswalk`):

- CNAE 2.0 → subsetor: 669 classes, pureza ponderada de 99,7%. CNAE 95 → subsetor: 562 classes, 99,8%.
- Reserva por grupo: 221 chaves, pureza ponderada de 99,0%, 214 aceitas. Por divisão: 60 chaves, 96,6%, 49 aceitas.
- A pureza é medida na amostra em que a correspondência é aprendida; ela não mede a exatidão da retroprojeção para 1994–2014.
- Antes da reserva, 7,5% a 9,6% do estoque de 1994–2001 ficava sem subsetor (classes CNAE 95 sem par). Depois, a parcela sem subsetor caiu para 4,0% em 1994, 0,6% em 1995 e valores próximos de zero a partir de 1996.
- Restam sem subsetor os vínculos sem nenhum código de atividade (2.056.163 no total, concentrados em 1985–1993 e em 1994) e 9 vínculos de 2006–2007.

**Transições da classificação** (`transicoes`):

- **2014 → 2015**: transição limpa. As participações dos subsetores mudam no máximo 0,4 ponto percentual.
- **2005 → 2006**: quase toda limpa, com exceção do subsetor `23`, que sobe 72,7% em 2006 (+1,9 pp) e cai 33,8% em 2007, enquanto o `24` perde 1,4 pp em 2006. Sugere vínculos migrando entre esses dois subsetores na codificação de 2006 (se `23` e `24` forem Ensino e Administração Pública, conferir no dicionário de layout).
- **1993 → 1994**: quebra clara. Vários subsetores variam de 20% a 80% (por exemplo, `24`: +77,0%, `23`: +183,9%) e outros caem cerca de 30%, com o estoque total crescendo 3,5%. Os subsetores 1985–1993 (definição nativa) e de 1994 em diante (derivados da CNAE) não são comparáveis em nível.
- Consequência: para análises por subsetor, tratar 1993/1994 como quebra de série e preferir 1995 em diante. A série total não é afetada.

### 5.2 Painéis finais (`painel`)

Duas versões, cada uma em um único arquivo (parquet e CSV):

**1. Com subsetor** (`painel_rais_mun_subsetor`):

| Coluna | Conteúdo |
|---|---|
| `ano` | ano da RAIS |
| `uf` | sigla do estado (PR, SC ou RS), obtida dos dois primeiros dígitos do código do município |
| `mun` | código do município, 6 dígitos (texto) |
| `subsetor` | subsetor IBGE harmonizado (`01` a `25`, além de `00`, `98` e `99`) |
| `estoque` | vínculos ativos em 31/12 no subsetor |

**2. Total por município** (`painel_rais_mun_total`): soma de todos os vínculos formais ativos em 31/12, por município e ano. Colunas `ano`, `uf`, `mun` e `estoque`. Não depende de classificação de atividade, inclui os vínculos sem atividade identificada e cobre os 41 anos. **É o painel usado no SCM.**

- A soma dos subsetores fecha com o total, ano a ano (o comando confere quando gera os dois).
- Os painéis são balanceados: toda combinação município (× subsetor) × ano aparece, com estoque 0 quando não há vínculos. Municípios criados no período aparecem com zeros antes da criação, e esses zeros são artificiais.
- O painel por subsetor tem 1.371.860 linhas (41 anos × 33.460 combinações), com 1.195 códigos de município (4 a mais que os 1.191 atuais de PR, SC e RS) e 28 categorias (`00`, `01` a `25`, `98` e `99`).
- O saldo (variação do estoque entre 31/12 de *t−1* e *t*, que não equivale ao saldo de admissões menos desligamentos do CAGED) e a coluna `quebra_classificacao` (1994, 2006 e 2015) ficam em `estoque_saldo_subsetor.parquet` e `estoque_saldo_total.parquet`, gerados pelo `build`.
- O CSV usa separador `;` e UTF-8 com BOM. O Excel remove os zeros à esquerda de `mun` e `subsetor` ao abrir o arquivo; em Stata, R e Python, ler essas colunas como texto.
- `--ano-inicial` corta o painel; cada execução sobrescreve o arquivo do seu nível, e o nome não registra a janela.

## 6. Etapa C: controle sintético (notebook)

### 6.1 Desenho

| Item | Escolha |
|---|---|
| Desfecho | Estoque de emprego formal em 31/12 (RAIS, todas as atividades), em nível |
| Unidades tratadas | Itapoá (código IBGE 4208450) e Navegantes (4211306) |
| Ano de tratamento | Primeiro ano de movimentação de carga: **2011** (Itapoá) e **2007** (Navegantes; valor inserido no notebook, a confirmar com a fonte) |
| Doadores | Municípios de SC com `IP = não` no banco original, sem zeros de emprego em nenhum ano do pré-tratamento |
| Período | 1995 a 2025 (16 anos de pré-tratamento para Itapoá e 12 para Navegantes) |
| Preditores | Somente defasagens: todos os valores do desfecho no pré-tratamento, como `special_predictors` |
| Estimador | `Synth` do `pysyncon`, com `optim_method='L-BFGS-B'` e `optim_initial='ols'` |
| Robustez | Nenhum teste nesta primeira rodada |

### 6.2 Como foi rodado

O notebook `SCM.ipynb` foi executado em Jupyter, célula a célula, **uma vez para cada município**, trocando `treated_mun` (`'Itapoá'` ou `'Navegantes'`) na célula de parâmetros. Cada execução foi exportada também como HTML (`SCM_outcome_<município>.html`), com as saídas.

### 6.3 Passos do notebook

1. **Parâmetros** (seção 1): dicionário `TREATED` (código IBGE e ano de tratamento), `treated_mun`, `first_year` (1995) e `last_year` (2025), caminhos dos arquivos e pasta de saída.
2. **Estoque da RAIS** (seção 2.1): lê `painel_rais_mun_total.parquet` e mantém `uf == 'SC'`.
3. **Códigos dos municípios** (seção 2.2): a RAIS usa 6 dígitos, e a tabela `mun_ibge.xlsx` traz o código de 7 dígitos e o nome. O vínculo é feito pelos 6 primeiros dígitos (sem colisões na tabela de SC). O notebook lista os códigos da RAIS sem par na tabela e os da tabela ausentes da RAIS.
4. **Indicador IP** (seção 2.3): lido de `bd_BA_ES_SC.xlsx`, aba `data`. O indicador não varia no tempo. O município tratado recebe `tratado`.
5. **Janela e doadores** (seção 2.4): uma tabela mostra quantos doadores restam para cada ano inicial possível, e o painel final é montado com o `first_year` escolhido. Doadores com estoque zero em algum ano do pré-tratamento (município ainda inexistente) são excluídos, e o painel é conferido como balanceado.
6. **Modelo principal** (seção 3): `Dataprep` e `Synth`, ATT, pesos dos doadores, série sintética, diferenças, RMSPE pré e pós e razão pós/pré.
7. **Gráficos** (seção 4): real × sintético e diferença (gap).

### 6.4 Arquivos de saída (por município)

Em `...\Resultados\Employment stock\<município>\`:

- `<município>_weights_controlmun.xlsx`: doadores com peso > 0,0001.
- `<município>_results.xlsx`: série real, sintética e diferença por ano.
- `<município>_effects.xlsx`: resumo (ano de tratamento, nº de doadores, diferença média pré e pós, RMSPE pré e pós e razão).
- `<município>_synthxreal.png` e `<município>_employment_gap.png`: gráficos.

### 6.5 Dados de entrada nesta rodada

- A RAIS de SC tem 296 códigos de município e 12.136 linhas (1985–2025). A tabela do IBGE tem 293 municípios de SC. Três códigos da RAIS não têm par: `421265`, `422000` e `429999`. Provavelmente são os municípios criados em 2013 (Pescaria Brava e Balneário Rincão, pelos códigos) e o código genérico de município ignorado, o que não foi confirmado.
- Indicador `IP` no banco original: 285 municípios de SC com `não` e 8 com `sim` (Balneário Camboriú, Imbituba, Itajaí, Itapoá, Navegantes, Piçarras, Porto Belo e São Francisco do Sul). Em cada execução, o município tratado é marcado como `tratado`, e os 7 restantes com `sim` ficam fora do doador (por exemplo, Navegantes na execução de Itapoá, e Itapoá na de Navegantes).
- Escolha do ano inicial (diagnóstico da seção 2.4): com início em 1985, Itapoá tem estoque zero em algum ano e há 192 doadores sem zeros; em 1990, 207; em 1995, 252; em 2000 e 2005, 285. Foi usado 1995.
- Doadores excluídos por zeros no pré-tratamento: 33 (de 285). **Doadores efetivos: 252**, nas duas execuções.
- Os dados de PR e RS da RAIS foram extraídos, mas o SCM desta rodada usou apenas municípios de SC.

### 6.6 Resultados (execução de 24/11/2026)

| | Itapoá (2011) | Navegantes (2007) |
|---|---|---|
| Anos de pré-tratamento | 16 (1995–2010) | 12 (1995–2006) |
| Doadores com peso > 0,0001 | 130 | 24 |
| Maiores pesos | Palhoça (3,3%), Águas de Chapecó (2,7%), São João Batista (1,7%) | São João Batista (13,2%), Ipuaçu (12,2%), Palhoça (11,3%) |
| ATT (média das diferenças pós) | 1.842 vínculos (`se` do pacote: 308) | 5.896 vínculos (`se` do pacote: 646) |
| Diferença média pré | −12,4 | −23,2 |
| RMSPE pré / pós | 109,8 / 2.173,0 | 265,0 / 6.501,7 |
| Razão pós/pré | 19,8 | 24,5 |
| Real × sintético em 2025 | 7.778 × 3.529 (+120%) | 30.698 × 20.502 (+50%) |


