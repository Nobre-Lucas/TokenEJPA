#!/usr/bin/env python3
"""
TokenEJPA - PoC v03: back-end minimo (Flask + SQLite) para o fluxo
cadastro -> inscricao em curso -> leitor de presenca com auto-inscricao
====================================================================

Por que agora tem back-end (as PoCs anteriores eram 100% client-side)?
-----------------------------------------------------------------------
O fluxo pedido nesta PoC tem tres telas que precisam enxergar o MESMO
estado, possivelmente em dispositivos diferentes:

  1. Cadastro de pessoa no tribunal (gera QR de identidade).
  2. Inscricao em curso (o aluno se inscreve, ou nao, em cada curso).
  3. Leitor de presenca (celular, configurado para "qual evento",
     precisa saber se a pessoa esta inscrita para decidir entre
     "confirmar presenca" ou "inscrever automaticamente e confirmar").

`localStorage` (usado nas PoCs v01/v02) e por navegador/aparelho - nao
da pra ter cadastro no notebook, inscricao em outra aba, e leitura no
celular, todos vendo a mesma coisa. Por isso esta PoC introduz um
back-end real (Flask), com SQLite como "banco de dados", igual ao que o
CLAUDE.md ja previa como caminho de evolucao ("back-end Python +
front-end Angular, a confirmar").

Efeito colateral bom: o SECRET do HMAC agora mora SO aqui no servidor.
As paginas HTML (cadastro/inscricao/leitor) nao tem mais o SECRET no
JS do navegador - o aviso de seguranca registrado em POC_v01/POC_v02
("qualquer um le o SECRET no codigo-fonte da pagina") deixa de existir
para o endpoint que importa (verificacao de presenca).

Mudanca de modelo importante: o QR agora identifica a PESSOA, nao mais
uma inscricao especifica (pessoa+curso) como em v01/v02. O vinculo com
o curso agora e decidido no momento da leitura (a pessoa esta ou nao
inscrita naquele curso), nao mais gravado dentro do proprio QR.

Como rodar (resumo - detalhes completos no README.md):
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python3 server.py
  Abra http://localhost:5000/

Variaveis de ambiente opcionais: TOKENEJPA_SECRET, TOKENEJPA_PORT,
TOKENEJPA_HTTPS, TOKENEJPA_DEBUG.
"""

import base64
import datetime
import hashlib
import hmac
import json
import os
import random
import socket
import sqlite3

from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tokenejpa_v03.db")
PAGINAS_DIR = os.path.join(BASE_DIR, "paginas")

# Segredo usado para assinar/verificar os tokens (HMAC-SHA256).
# Defina TOKENEJPA_SECRET com um valor proprio e aleatorio. Se nao definir,
# usa-se um valor de DESENVOLVIMENTO publico (qualquer pessoa que leia este
# repositorio consegue forjar tokens assinados com ele) - serve so para
# experimentar localmente. Trocar o segredo invalida os QR Codes ja emitidos.
_SECRET_PADRAO = "TokenEJPA-PoC-v03-2026-troque-antes-de-usar-de-verdade"
SECRET = os.environ.get("TOKENEJPA_SECRET") or _SECRET_PADRAO
USANDO_SECRET_PADRAO = SECRET == _SECRET_PADRAO

# Cursos de teste hardcoded (substituem um cadastro/API real de cursos,
# que ainda nao existe no projeto). Mantidos com os mesmos IDs da v01/v02
# para nao quebrar continuidade dos QRs ja gerados nas PoCs anteriores.
CURSOS = [
    {"curso_id": "OFICINA-2026-01", "nome": "Oficina de Prototipagem Agil"},
    {"curso_id": "CURSO-2026-EJPA", "nome": "Curso EJPA - Turma 2026"},
]
CURSOS_POR_ID = {c["curso_id"]: c for c in CURSOS}

app = Flask(__name__, static_folder=None)


# ---------------------------------------------------------------------
# banco de dados (SQLite - "banco de dados" real desta PoC, mas ainda
# um arquivo local; nao pensado para concorrencia pesada nem backup)
# ---------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def fechar_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def inicializar_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pessoas (
            mat TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            rg TEXT,
            cpf TEXT,
            admissao TEXT,
            criado_em TEXT,
            token TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inscricoes (
            mat TEXT NOT NULL,
            curso_id TEXT NOT NULL,
            criado_em TEXT,
            auto INTEGER DEFAULT 0,
            PRIMARY KEY (mat, curso_id)
        );

        CREATE TABLE IF NOT EXISTS presencas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mat TEXT NOT NULL,
            curso_id TEXT NOT NULL,
            hora TEXT,
            auto_inscrita INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------
# token assinado (mesmo esquema HMAC das PoCs anteriores, so que agora
# gerado E verificado no mesmo lugar: aqui no servidor)
# ---------------------------------------------------------------------

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(texto: str) -> bytes:
    pad = "=" * (-len(texto) % 4)
    return base64.urlsafe_b64decode(texto + pad)


def gerar_token(mat: str, nome: str):
    payload = {
        "mat": mat,
        "nome": nome,
        "iat": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    payload_b64 = b64url_encode(payload_json.encode("utf-8"))
    assinatura = hmac.new(SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()[:16]
    token = payload_b64 + "." + b64url_encode(assinatura)
    return token, payload


def verificar_token(token: str):
    """Retorna o payload (dict) se a assinatura bater, ou None se invalido."""
    if not token or "." not in token:
        return None
    payload_b64, _, assinatura_b64 = token.partition(".")
    assinatura_esperada = hmac.new(
        SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()[:16]
    assinatura_calculada_b64 = b64url_encode(assinatura_esperada)
    if not hmac.compare_digest(assinatura_calculada_b64, assinatura_b64):
        return None
    try:
        return json.loads(b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------
# geradores de dados ficticios (crachá simulado - nunca dados reais)
# ---------------------------------------------------------------------

def gerar_rg_ficticio() -> str:
    return f"{random.randint(1000000, 9999999)} SSP-PA"


def gerar_cpf_ficticio() -> str:
    # Formato de CPF, mas SEM digito verificador valido de proposito -
    # e so pra preencher o layout do cracha simulado, nunca um CPF real.
    partes = [random.randint(0, 999) for _ in range(3)]
    verificador = random.randint(0, 99)
    return f"{partes[0]:03d}.{partes[1]:03d}.{partes[2]:03d}-{verificador:02d}"


def gerar_admissao_ficticia() -> str:
    inicio = datetime.date(2010, 1, 1)
    fim = datetime.date.today()
    dias = (fim - inicio).days
    data = inicio + datetime.timedelta(days=random.randint(0, dias))
    return data.strftime("%d/%m/%Y")


def proxima_matricula(db) -> str:
    linha = db.execute(
        "SELECT COALESCE(MAX(CAST(mat AS INTEGER)), 100000) AS maior FROM pessoas"
    ).fetchone()
    return str(linha["maior"] + 1)


def agora_iso() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------
# paginas (HTML servido como arquivo estatico, sem Jinja - evita
# qualquer conflito entre o JS embutido nas paginas e a sintaxe do Jinja)
# ---------------------------------------------------------------------

@app.route("/")
def pagina_inicial():
    return send_from_directory(PAGINAS_DIR, "inicio.html")


@app.route("/cadastro")
def pagina_cadastro():
    return send_from_directory(PAGINAS_DIR, "cadastro.html")


@app.route("/inscricao")
def pagina_inscricao():
    return send_from_directory(PAGINAS_DIR, "inscricao.html")


@app.route("/leitor")
def pagina_leitor():
    return send_from_directory(PAGINAS_DIR, "leitor.html")


# ---------------------------------------------------------------------
# API - pessoas / cadastro
# ---------------------------------------------------------------------

@app.route("/api/pessoas", methods=["GET", "POST"])
def api_pessoas():
    db = get_db()

    if request.method == "POST":
        dados = request.get_json(silent=True) or {}
        nome = (dados.get("nome") or "").strip()
        if not nome:
            return jsonify({"erro": "Informe o nome da pessoa."}), 400

        mat = proxima_matricula(db)
        rg = gerar_rg_ficticio()
        cpf = gerar_cpf_ficticio()
        admissao = gerar_admissao_ficticia()
        token, _payload = gerar_token(mat, nome)
        criado_em = agora_iso()

        db.execute(
            "INSERT INTO pessoas (mat, nome, rg, cpf, admissao, criado_em, token) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mat, nome, rg, cpf, admissao, criado_em, token),
        )
        db.commit()

        return jsonify(
            {
                "mat": mat, "nome": nome, "rg": rg, "cpf": cpf,
                "admissao": admissao, "criado_em": criado_em, "token": token,
            }
        ), 201

    linhas = db.execute(
        "SELECT mat, nome, rg, cpf, admissao, criado_em, token FROM pessoas ORDER BY CAST(mat AS INTEGER) DESC"
    ).fetchall()
    return jsonify([dict(linha) for linha in linhas])


@app.route("/api/pessoas/<mat>")
def api_pessoa_por_matricula(mat):
    db = get_db()
    pessoa = db.execute("SELECT mat, nome FROM pessoas WHERE mat = ?", (mat,)).fetchone()
    if not pessoa:
        return jsonify({"erro": "Matricula nao encontrada."}), 404

    inscricoes = db.execute(
        "SELECT curso_id, auto FROM inscricoes WHERE mat = ?", (mat,)
    ).fetchall()
    inscrito_em = {linha["curso_id"]: bool(linha["auto"]) for linha in inscricoes}

    return jsonify({"mat": pessoa["mat"], "nome": pessoa["nome"], "inscrito_em": inscrito_em})


# ---------------------------------------------------------------------
# API - cursos (lista fixa desta PoC)
# ---------------------------------------------------------------------

@app.route("/api/cursos")
def api_cursos():
    return jsonify(CURSOS)


# ---------------------------------------------------------------------
# API - inscricoes (feita manualmente pelo "aluno" no portal de inscricao)
# ---------------------------------------------------------------------

@app.route("/api/inscricoes", methods=["POST"])
def api_inscricoes():
    db = get_db()
    dados = request.get_json(silent=True) or {}
    mat = (dados.get("mat") or "").strip()
    curso_id = (dados.get("curso_id") or "").strip()

    pessoa = db.execute("SELECT mat FROM pessoas WHERE mat = ?", (mat,)).fetchone()
    if not pessoa:
        return jsonify({"erro": "Matricula nao encontrada."}), 404
    if curso_id not in CURSOS_POR_ID:
        return jsonify({"erro": "Curso invalido."}), 400

    ja_existia = db.execute(
        "SELECT 1 FROM inscricoes WHERE mat = ? AND curso_id = ?", (mat, curso_id)
    ).fetchone()

    if not ja_existia:
        db.execute(
            "INSERT INTO inscricoes (mat, curso_id, criado_em, auto) VALUES (?, ?, ?, 0)",
            (mat, curso_id, agora_iso()),
        )
        db.commit()

    return jsonify({"ok": True, "ja_existia": bool(ja_existia)})


# ---------------------------------------------------------------------
# API - presenca (o coracao da PoC v03: le o QR, decide se confirma ou
# se inscreve automaticamente + confirma)
# ---------------------------------------------------------------------

@app.route("/api/presenca", methods=["POST"])
def api_presenca():
    db = get_db()
    dados = request.get_json(silent=True) or {}
    token = dados.get("token") or ""
    curso_id = (dados.get("curso_id") or "").strip()

    if not curso_id or curso_id not in CURSOS_POR_ID:
        return jsonify({"status": "invalido", "motivo": "Selecione o curso desta sessao de leitura."}), 400

    payload = verificar_token(token)
    if payload is None:
        return jsonify({"status": "invalido", "motivo": "QR invalido: assinatura nao confere ou token malformado."}), 200

    mat = payload.get("mat")
    nome = payload.get("nome")
    pessoa = db.execute("SELECT mat, nome FROM pessoas WHERE mat = ?", (mat,)).fetchone()
    if not pessoa:
        return jsonify({"status": "invalido", "motivo": "Matricula do QR nao esta cadastrada no sistema."}), 200

    curso = CURSOS_POR_ID[curso_id]

    inscrita = db.execute(
        "SELECT 1 FROM inscricoes WHERE mat = ? AND curso_id = ?", (mat, curso_id)
    ).fetchone()

    inscrita_agora = False
    if not inscrita:
        db.execute(
            "INSERT INTO inscricoes (mat, curso_id, criado_em, auto) VALUES (?, ?, ?, 1)",
            (mat, curso_id, agora_iso()),
        )
        inscrita_agora = True

    ja_tinha_presenca = db.execute(
        "SELECT 1 FROM presencas WHERE mat = ? AND curso_id = ?", (mat, curso_id)
    ).fetchone()

    hora = agora_iso()
    if ja_tinha_presenca and not inscrita_agora:
        status = "repetida"
    else:
        db.execute(
            "INSERT INTO presencas (mat, curso_id, hora, auto_inscrita) VALUES (?, ?, ?, ?)",
            (mat, curso_id, hora, 1 if inscrita_agora else 0),
        )
        status = "inscrita_e_presente" if inscrita_agora else "presente"

    db.commit()

    return jsonify(
        {
            "status": status,
            "pessoa": {"mat": pessoa["mat"], "nome": pessoa["nome"]},
            "curso": curso,
            "hora": hora,
        }
    )


@app.route("/api/presencas")
def api_listar_presencas():
    db = get_db()
    curso_id = request.args.get("curso_id")

    sql = (
        "SELECT p.id, p.mat, pe.nome, p.curso_id, p.hora, p.auto_inscrita "
        "FROM presencas p JOIN pessoas pe ON pe.mat = p.mat "
    )
    parametros = ()
    if curso_id:
        sql += "WHERE p.curso_id = ? "
        parametros = (curso_id,)
    sql += "ORDER BY p.id DESC"

    linhas = db.execute(sql, parametros).fetchall()
    resultado = []
    for linha in linhas:
        curso = CURSOS_POR_ID.get(linha["curso_id"], {"curso_id": linha["curso_id"], "nome": linha["curso_id"]})
        resultado.append(
            {
                "id": linha["id"], "mat": linha["mat"], "nome": linha["nome"],
                "curso_id": linha["curso_id"], "curso_nome": curso["nome"],
                "hora": linha["hora"], "auto_inscrita": bool(linha["auto_inscrita"]),
            }
        )
    return jsonify(resultado)


# ---------------------------------------------------------------------
# API - reset (nao existe para pessoas/cadastro, de proposito)
# ---------------------------------------------------------------------

@app.route("/api/reset/inscricoes", methods=["POST"])
def api_reset_inscricoes():
    """Reset "grande": limpa inscricoes E presencas, mantem as pessoas
    cadastradas (para nao ter que recriar QRs entre rodadas de teste)."""
    db = get_db()
    db.execute("DELETE FROM inscricoes")
    db.execute("DELETE FROM presencas")
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/reset/presencas", methods=["POST"])
def api_reset_presencas():
    """Reset "pequeno": limpa so o historico de presencas (uteis para
    repetir o teste de leitura sem mexer em quem esta inscrito ou nao)."""
    db = get_db()
    db.execute("DELETE FROM presencas")
    db.commit()
    return jsonify({"ok": True})


def descobrir_ip_local() -> str:
    """Melhor esforco para achar o IP da maquina na rede local (LAN) -
    so para exibir uma dica de qual endereco usar no celular. Nao afeta
    nada do funcionamento do servidor em si."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    inicializar_db()

    # Camera em navegador exige contexto seguro (HTTPS ou localhost).
    # - Uso so no computador que roda o servidor: http://localhost funciona.
    # - Uso a partir de outro aparelho (celular) na mesma rede: ative
    #   TOKENEJPA_HTTPS=1 (certificado autoassinado; requer `cryptography`).
    usar_https = os.environ.get("TOKENEJPA_HTTPS") == "1"
    ssl_context = "adhoc" if usar_https else None
    protocolo = "https" if usar_https else "http"
    porta = int(os.environ.get("TOKENEJPA_PORT", "5000"))
    # O modo debug do Flask expoe um console interativo; so ligue de proposito
    # e nunca em rede compartilhada.
    debug = os.environ.get("TOKENEJPA_DEBUG") == "1"

    print(f"Banco de dados: {DB_PATH}")
    print(f"Servidor em {protocolo}://0.0.0.0:{porta}  (paginas: /cadastro, /inscricao, /leitor)")
    if USANDO_SECRET_PADRAO:
        print("AVISO: usando o SECRET padrao de desenvolvimento. Defina TOKENEJPA_SECRET")
        print("       para qualquer uso alem de um teste local isolado.")
    if usar_https:
        print(f"Acesse do celular (mesma rede): {protocolo}://{descobrir_ip_local()}:{porta}/leitor")
        print("Certificado autoassinado: o navegador vai avisar 'nao confiavel' na primeira")
        print("visita - aceite o risco/avance mesmo assim (uma vez por navegador/aparelho).")
    else:
        print("HTTPS desativado (uso local via localhost). Para testar no celular, rode com")
        print("TOKENEJPA_HTTPS=1 (ver README.md).")

    app.run(host="0.0.0.0", port=porta, debug=debug, ssl_context=ssl_context)
