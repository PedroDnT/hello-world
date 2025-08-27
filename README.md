# Assistente Jurídico DataJud – Web Service

Este repositório contém **um serviço web** que combina a **API Pública do DataJud (CNJ)** com modelos **OpenAI** para responder, em português, perguntas sobre processos judiciais.  
Ele foi pensado para **deploy 1-click no Render** – mas roda localmente com `python app.py`.

---

## Sumário

1. [Funcionalidades](#funcionalidades)  
2. [Arquitetura](#arquitetura)  
3. [Pré-requisitos](#pré-requisitos)  
4. [Instalação local](#instalação-local)  
5. [Uso local](#uso-local)  
6. [Deploy no Render](#deploy-no-render)  
7. [Exemplos de uso](#exemplos-de-uso)  
8. [Possíveis melhorias](#possíveis-melhorias)

---

## Funcionalidades

| Tool (function)                 | O que faz                                                                                           |
|---------------------------------|------------------------------------------------------------------------------------------------------|
| `search_process_by_number`      | Busca um processo pelo número (CNJ) em um ou vários tribunais                                        |
| `get_process_status`            | Informa status, último movimento e situação (em andamento, arquivado, julgado…)                     |
| `get_process_movements`         | Lista movimentos processuais com complementos tabelados                                             |
| `get_process_details`           | Ficha completa do processo (classe, assuntos, órgão julgador, sistema, etc.)                        |
| `search_by_class_and_judge`     | Pesquisa processos por **classe processual** e **órgão julgador** com suporte a paginação           |

> Tribunais suportados nesta versão: **TJSP**, **STJ** e **TRF1-TRF6**.  
> Para adicionar outro tribunal basta inserir seu *alias* no dicionário `COURTS` em `app.py`.

---

## Arquitetura

```
┌──────────────┐   texto   ┌──────────────────────────┐
│   Usuário    │─────────►│  Agent (GPT-4 Turbo)     │
└──────────────┘          │  · escolhe ferramenta     │
        ▲                 │  · chama função Python    │
        │ resposta        └────────┬──────────────────┘
        │                         │
        │                 chama   ▼
┌───────────────────┐    JSON  ┌────────────────────────┐
│  Funções DataJud  │◄────────►│  API Pública DataJud   │
└───────────────────┘           └────────────────────────┘
```

* **OpenAI function-calling** decide qual tool executar.  
* Funções Python geram Query DSL, chamam DataJud, traduzem códigos e formatam datas.  
* Serviço exposto via **Flask + Gunicorn**.

---

## Pré-requisitos

| Item              | Detalhe                         |
|-------------------|---------------------------------|
| Python            | 3.8 ou superior                 |
| OpenAI API Key    | variável `OPENAI_API_KEY`       |
| Chave Pública CNJ | já incluída, pode ser alterada¹ |

¹ Se o CNJ mudar a chave, exporte `DATAJUD_API_KEY` ou edite a constante `API_KEY` em `app.py`.

---

## Instalação local

```bash
git clone https://github.com/PedroDnT/hello-world.git
cd hello-world

# (Opcional) ambiente virtual
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Crie um arquivo `.env`:

```
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
# DATAJUD_API_KEY=xxxxxxxx  # opcional
FLASK_SECRET_KEY=suaSecretKeyAqui
```

---

## Uso local

```bash
python app.py            # roda em http://localhost:8080
# ou
gunicorn app:app -b 0.0.0.0:8080
```

Abra o navegador em `http://localhost:8080`.  
Também é possível consumir pelas rotas REST:

```
POST /api/chat                {"query": "..."}
GET  /api/process/<numero>?court=TRF1
GET  /api/movements/<numero>?court=TJSP&limit=15
GET  /api/details/<numero>?court=STJ
GET  /api/search?class_code=1116&judge_code=13597&court=TJSP&limit=20
```

---

## Deploy no Render

1. **Fork/clone** o repositório para sua conta GitHub.  
2. Acesse **dashboard.render.com ➜ New ➜ Web Service**  
3. Conecte seu repositório e escolha:
   * Build command: `pip install -r requirements.txt`
   * Start command: **`gunicorn app:app`**  (já definido no `Procfile`)
   * Runtime: Python 3.11 (ou versão compatível)
4. Em **Environment ➜ Add Environment Variable** adicione:
   * `OPENAI_API_KEY` • sua chave OpenAI  
   * (Opcional) `DATAJUD_API_KEY` se quiser substituir a pública  
   * `FLASK_SECRET_KEY` • string aleatória
5. Clique **Create Web Service** e aguarde o deploy 💡  
6. A URL pública exibirá a interface de chat; `/health` retorna status 200.

> Render expõe portas automaticamente a partir do `gunicorn`.  
> Logs podem ser vistos em **Logs ➜ Build/Service**.

---

## Exemplos de uso

* **Status de processo**  
  “Qual o status do processo `00008323520184013202`?”  

* **Movimentos recentes**  
  “Quais foram os últimos 5 movimentos do processo `00008323520184013202` no TRF1?”  

* **Pesquisa por classe/vara**  
  “Busque processos da classe 1116 no órgão julgador 13597 no TJSP, limite 20.”  

* **Detalhes completos**  
  “Me dê detalhes completos do processo `00008323520184013202`.”

---

## Possíveis melhorias

* Interface **Streamlit** ou **Next.js**  
* **Cache Redis** para reduzir chamadas ao CNJ  
* Suporte a **Justiça do Trabalho / Eleitoral / Militar**  
* Geração de **relatórios PDF** com andamentos  
* **Embeddings** para sugerir jurisprudência similar  

Contribuições são bem-vindas! Abra uma _issue_ ou envie um _pull request_.  
Feito com ☕, código aberto e ❤️ pela comunidade.
