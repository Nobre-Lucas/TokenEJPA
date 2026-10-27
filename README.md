# TokenEJPA

Protótipo (prova de conceito) de um mecanismo de **registro de presença em cursos, aulas e oficinas** em que a pessoa se apresenta ao leitor — com um QR Code — e a presença é registrada automaticamente, **sem login e senha a cada leitura**.

> **Status:** protótipo para demonstração e validação de ideias. **Não é um sistema de produção** (veja [Limitações e avisos de segurança](#limitações-e-avisos-de-segurança)). Todos os dados usados são **fictícios**.

## Sumário

- [Como funciona](#como-funciona)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Executando](#executando)
- [Roteiro de teste passo a passo](#roteiro-de-teste-passo-a-passo)
- [Testando a leitura de QR Code com o celular](#testando-a-leitura-de-qr-code-com-o-celular)
- [Configuração (variáveis de ambiente)](#configuração-variáveis-de-ambiente)
- [Estrutura do projeto](#estrutura-do-projeto)
- [API HTTP](#api-http)
- [Solução de problemas](#solução-de-problemas)
- [Limitações e avisos de segurança](#limitações-e-avisos-de-segurança)
- [Próximos passos](#próximos-passos)

## Como funciona

O protótipo tem um back-end (Flask + SQLite) e três telas web servidas pelo próprio back-end:

| Tela | Endereço | Para que serve |
|---|---|---|
| Início | `/` | Índice com links para as demais telas. |
| Cadastro | `/cadastro` | Cadastra uma pessoa (você digita só o nome; matrícula, RG, CPF e data de admissão são **gerados de forma fictícia**) e gera o **QR Code de identidade** dela. O QR pode ser baixado em PNG. |
| Inscrição | `/inscricao` | Busca a pessoa pela matrícula e a inscreve (ou não) nos cursos disponíveis. Também permite resetar inscrições e presenças. |
| Leitor | `/leitor` | Abre a câmera, lê o QR Code e registra a presença no curso selecionado. |

**Ideia central:** cada pessoa tem **um único QR Code** (não um por curso). Ao ler o QR, o servidor decide:

1. Verifica a **assinatura** do QR (HMAC-SHA256). QR adulterado ou de origem desconhecida é rejeitado (`invalido`).
2. Confere se a matrícula existe no cadastro.
3. Se a pessoa **já está inscrita** no curso do leitor → registra presença (`presente`, ou `repetida` se já havia presença).
4. Se **não está inscrita** → inscreve automaticamente **e** registra presença (`inscrita_e_presente`).

O QR contém um token compacto no formato `base64url(payload_json).base64url(assinatura)`, onde o payload tem matrícula, nome e data de emissão. A assinatura é calculada **apenas no servidor** (o segredo nunca vai para o navegador).

Os cursos disponíveis são fixos no código (`CURSOS` em `server.py`): `OFICINA-2026-01` e `CURSO-2026-EJPA`.

## Requisitos

**No computador que vai rodar o servidor:**

- **Python 3.9 ou superior** (com `pip` e o módulo `venv`).
  - Debian/Ubuntu: `sudo apt install python3 python3-venv python3-pip`
  - Windows: instale o Python em <https://www.python.org/downloads/> (marque *Add python.exe to PATH*).
  - macOS: `brew install python` ou instalador oficial.
- Acesso à internet **durante a instalação** (para baixar as dependências Python).
- Um navegador moderno (Chrome, Edge, Firefox, Safari).

**Para usar o leitor (câmera):**

- Um aparelho com **câmera** (celular ou notebook com webcam).
- **Acesso à internet no aparelho que abre a tela do leitor e a tela de cadastro**: elas carregam bibliotecas JavaScript por CDN (`jsQR` e `qrcode`, via `cdn.jsdelivr.net`). Sem internet — ou com `cdn.jsdelivr.net` bloqueado — o QR não é gerado/lido.
- Contexto seguro (HTTPS ou `localhost`), exigência dos navegadores para acessar a câmera. Veja [a seção do celular](#testando-a-leitura-de-qr-code-com-o-celular).

Dependências Python (instaladas via `requirements.txt`): `flask` e `cryptography`.

## Instalação

```bash
# 1. Obtenha o código
git clone <URL-DESTE-REPOSITORIO>
cd <pasta-do-repositorio>

# 2. Crie e ative um ambiente virtual
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows (PowerShell)
# .venv\Scripts\activate.bat       # Windows (cmd)

# 3. Instale as dependências
pip install -r requirements.txt
```

> No Windows o comando do Python costuma ser `python` (ou `py`) em vez de `python3`.

## Executando

```bash
python3 server.py
```

O terminal mostra algo como:

```
Banco de dados: .../tokenejpa_v03.db
Servidor em http://0.0.0.0:5000  (paginas: /cadastro, /inscricao, /leitor)
```

Abra <http://localhost:5000/> no navegador. Pare o servidor com `Ctrl + C`.

- O **banco de dados SQLite é criado automaticamente** na primeira execução (arquivo `tokenejpa_v03.db`, ao lado do `server.py`). Para recomeçar do zero, pare o servidor e apague esse arquivo.
- Usando só `http://localhost:5000` no próprio computador, **não é preciso HTTPS**: `localhost` já é contexto seguro e a webcam funciona.
- Para ler o QR com o **celular**, siga a [seção abaixo](#testando-a-leitura-de-qr-code-com-o-celular).

## Roteiro de teste passo a passo

1. Suba o servidor e abra `/cadastro`. Cadastre **duas pessoas** (ex.: *Fulano de Tal* e *Ciclana Souza*). Baixe o PNG do QR de cada uma (ou anote a matrícula para reabrir depois). Não existe botão de reset no cadastro, de propósito: as pessoas e os QR já emitidos continuam válidos entre as rodadas de teste.
2. Abra `/inscricao`, busque a primeira pessoa pela matrícula e inscreva-a em **um** dos cursos. Faça o inverso com a segunda (outro curso, ambos, ou nenhum — qualquer combinação é aceita).
3. Abra `/leitor`, selecione o curso em que a primeira pessoa **está** inscrita, inicie a câmera e aponte para o QR dela (na tela de outro aparelho ou impresso). Resultado esperado: **"Presença registrada"** (verde).
4. Troque o curso no seletor do leitor para aquele em que a pessoa **não** está inscrita e leia de novo. Resultado: **"Você foi inscrito no curso X e sua presença foi confirmada"** (azul). A inscrição passa a aparecer em `/inscricao` marcada como automática.
5. Leia o mesmo QR novamente no mesmo curso: **"Presença já registrada anteriormente"** (amarelo).
6. Teste os extremos: pessoa sem nenhuma inscrição; pessoa inscrita nos dois cursos; QR adulterado (deve ser **rejeitado**).

**Botões de reset**

| Onde | Botão | Efeito |
|---|---|---|
| `/inscricao` | Resetar inscrições e presenças | Apaga **todas** as inscrições e presenças (mantém as pessoas). |
| `/leitor` | Resetar presenças | Apaga só as presenças (mantém as inscrições). |

## Testando a leitura de QR Code com o celular

Navegadores só liberam a câmera em **HTTPS ou `localhost`**. Se você abrir `http://<ip-do-computador>:5000` no celular, a câmera será bloqueada. Há três formas de contornar:

### Opção A — HTTPS autoassinado na rede local (recomendada)

Computador e celular precisam estar na **mesma rede**.

```bash
# Linux / macOS
TOKENEJPA_HTTPS=1 python3 server.py

# Windows (PowerShell)
$env:TOKENEJPA_HTTPS = "1"; python server.py
```

O terminal imprime o endereço para o celular, por exemplo `https://192.168.x.x:5000/leitor`. No celular:

1. Abra esse endereço.
2. O navegador avisará que o certificado **não é confiável** (é autoassinado — esperado). Avance mesmo assim:
   - Chrome: *Avançado* → *Ir para o site mesmo assim*.
   - Firefox: *Avançado* → *Aceitar o risco e continuar*.
   - Safari: *Mostrar detalhes* → *Visitar este site*.
3. Permita o acesso à câmera quando solicitado.

O aviso de certificado aparece uma vez por navegador/aparelho.

**Se o celular não conseguir abrir o endereço**, as causas mais comuns são:

- **Firewall do computador bloqueando a porta 5000.** Libere-a temporariamente. Exemplo no Linux com `ufw`:
  ```bash
  sudo ufw allow 5000/tcp
  # ao terminar os testes:
  sudo ufw delete allow 5000/tcp
  ```
  No Windows, aceite o prompt do Firewall do Windows na primeira execução (redes privadas) ou crie uma regra de entrada para a porta TCP 5000.
- **Isolamento de clientes na rede Wi-Fi** ("AP/client isolation"), comum em redes corporativas, de eventos e de visitantes: a rede impede que um aparelho enxergue outro. Teste em outra rede ou use o **hotspot do celular**: ligue o computador no hotspot do próprio celular e acesse o endereço mostrado no terminal.
- Computador e celular em **redes diferentes** (ex.: um no cabo/VLAN e outro no Wi-Fi de convidados).

### Opção B — Cabo USB com `adb reverse` (Android)

Não depende da rede Wi-Fi nem de HTTPS: o celular passa a enxergar o servidor como `localhost`.

1. Instale o [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools) e ative a *Depuração USB* no celular.
2. Conecte o cabo e rode: `adb reverse tcp:5000 tcp:5000`
3. Com o servidor rodando **sem** `TOKENEJPA_HTTPS`, abra `http://localhost:5000/leitor` no navegador do celular.

### Opção C — Túnel público temporário

Serviços como [ngrok](https://ngrok.com/) ou [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) geram um link `https://` para a porta 5000 (ex.: `cloudflared tunnel --url http://localhost:5000`). Com esse link, rode o servidor **sem** `TOKENEJPA_HTTPS`. Atenção: o protótipo ficará acessível pela internet a quem tiver o link, sem autenticação — use só com dados fictícios e por pouco tempo. Esses serviços podem ser bloqueados por firewalls/proxies corporativos.

## Configuração (variáveis de ambiente)

Todas são opcionais.

| Variável | Padrão | Descrição |
|---|---|---|
| `TOKENEJPA_SECRET` | segredo de desenvolvimento público | Segredo usado para assinar/verificar os QR Codes. **Defina um valor próprio e aleatório** se o servidor ficar acessível a outras pessoas (ex.: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). Ao trocá-lo, os QR já emitidos deixam de valer. |
| `TOKENEJPA_PORT` | `5000` | Porta do servidor. |
| `TOKENEJPA_HTTPS` | desligado | `1` ativa HTTPS com certificado autoassinado (necessário para a câmera no celular via rede local). |
| `TOKENEJPA_DEBUG` | desligado | `1` ativa o modo debug do Flask (recarrega ao editar o código). **Nunca use em rede compartilhada**: expõe um console interativo. |

Exemplo:

```bash
TOKENEJPA_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
TOKENEJPA_HTTPS=1 python3 server.py
```

(Se o segredo for gerado a cada execução, os QR Codes anteriores deixam de ser válidos. Para manter os QR entre execuções, guarde o valor e reutilize-o.)

## Estrutura do projeto

```
.
├── server.py            # Back-end Flask + SQLite (API e servidor das páginas)
├── requirements.txt     # Dependências Python
├── paginas/
│   ├── inicio.html      # Índice
│   ├── cadastro.html    # Cadastro de pessoas + geração do QR
│   ├── inscricao.html   # Inscrição em cursos + reset
│   └── leitor.html      # Leitor de presença (câmera + jsQR)
└── tokenejpa_v03.db     # Criado automaticamente na 1ª execução (ignorado pelo git)
```

## API HTTP

Todas as respostas são JSON. As páginas usam esta mesma API (mesma origem, sem CORS).

| Método e rota | Descrição |
|---|---|
| `GET /api/cursos` | Lista os cursos disponíveis. |
| `GET /api/pessoas` | Lista as pessoas cadastradas. |
| `POST /api/pessoas` | Cadastra uma pessoa. Corpo: `{"nome": "..."}`. Retorna os dados fictícios gerados e o `token` do QR. |
| `GET /api/pessoas/<mat>` | Dados e inscrições de uma pessoa. |
| `POST /api/inscricoes` | Inscreve uma pessoa em um curso. |
| `POST /api/presenca` | Corpo: `{"token": "...", "curso_id": "..."}`. Valida o token e registra presença. `status`: `presente`, `repetida`, `inscrita_e_presente` ou `invalido`. |
| `GET /api/presencas` | Histórico de presenças. |
| `POST /api/reset/presencas` | Apaga as presenças. |
| `POST /api/reset/inscricoes` | Apaga inscrições e presenças. |

Exemplo rápido:

```bash
curl -X POST http://localhost:5000/api/pessoas \
     -H 'Content-Type: application/json' -d '{"nome":"Fulano de Tal"}'
```

## Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| A câmera não abre / "permissão negada" | Página aberta por `http://` com IP da rede. Use `localhost`, HTTPS (Opção A) ou `adb reverse` (Opção B). Verifique também a permissão de câmera do navegador. |
| Celular: "não foi possível conectar" | Firewall do computador, isolamento de clientes no Wi-Fi ou redes diferentes. Veja a Opção A. |
| `TypeError: Using ad-hoc certificates requires the cryptography library` | Rode `pip install -r requirements.txt` dentro do ambiente virtual ativo. |
| `ModuleNotFoundError: No module named 'flask'` | O ambiente virtual não está ativo ou as dependências não foram instaladas. |
| `Address already in use` | Outra aplicação usa a porta 5000 (no macOS, o AirPlay Receiver). Use `TOKENEJPA_PORT=5001`. |
| QR aparece em branco / leitor não decodifica | O aparelho não conseguiu carregar as bibliotecas do CDN (`cdn.jsdelivr.net`). Verifique a internet. |
| QR de ontem agora é "inválido" | O `TOKENEJPA_SECRET` mudou entre as execuções. |
| Leitura difícil | Aumente o brilho da tela que exibe o QR, evite reflexos, mantenha o QR inteiro dentro do quadro e a ~15–30 cm da câmera. |

## Limitações e avisos de segurança

Este protótipo existe para **validar o fluxo**, não para uso real. Em particular:

- **Sem autenticação** nas telas de cadastro e inscrição (a pessoa é identificada só pela matrícula) e nas rotas da API. Qualquer pessoa que alcance o servidor pode cadastrar, inscrever e resetar dados. Não o exponha à internet nem a redes não confiáveis.
- **Segredo de assinatura padrão é público** (está no código-fonte). Defina `TOKENEJPA_SECRET` para qualquer uso fora de um teste local isolado.
- **Sem expiração ou revogação** de QR Codes (o campo `iat` existe no token, mas não é verificado). Quem tiver a imagem do QR de alguém pode usá-la.
- O token é **assinado, mas não criptografado**: matrícula e nome ficam legíveis para quem decodificar o QR.
- Cursos fixos no código, sem edição/exclusão de pessoas, sem perfis de acesso.
- Banco SQLite local, sem backup nem pensado para concorrência pesada.
- O servidor Flask embutido é de desenvolvimento; para produção seria necessário um servidor WSGI, HTTPS com certificado válido, autenticação e uma política de proteção de dados pessoais.
- **Use apenas dados fictícios.** Os dados gerados pelo cadastro (RG, CPF, admissão) são inventados e não passam por validação de documentos reais.

## Próximos passos

- Autenticação e perfis de acesso (administrador, instrutor, aluno).
- Expiração/revogação de QR Codes e uso de assinatura assimétrica.
- Cadastro de cursos e fonte real de inscrições; integração com os sistemas da instituição.
- Front-end definitivo (possivelmente Angular) e relatórios de presença.
- Empacotar as bibliotecas JavaScript localmente para funcionar sem internet.
- Método complementar de identificação (por exemplo, leitura da matrícula impressa no crachá via OCR).
