from flask import Flask, render_template, request, session, jsonify, redirect, url_for, flash
import requests
import os
import uuid
import smtplib
import ssl
from email.message import EmailMessage
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = "goldenclick"

API_SOURCES = {
    "dummyjson": "https://dummyjson.com/products?limit=100",
    "fakestore": "https://fakestoreapi.com/products",
    # alias para evitar confusão com o nome "fake story"
    "fake_story": "https://fakestoreapi.com/products"
}
DEFAULT_API = "dummyjson"

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").strip().lower() in ["1", "true", "yes", "on"]
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "goldenclick88@gmail.com")
DEFAULT_EMAIL_PASSWORD = "joza iyrg smtp gikp"  # senha de app fornecida
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", DEFAULT_EMAIL_PASSWORD).strip()  # configurar via variável de ambiente


def gerar_codigo():
    return uuid.uuid4().hex[:8].upper()


def obter_api_url(api_nome):
    # suportar variações de nome para FakeStore da descrição "fake story"
    if api_nome == "fake story":
        api_nome = "fake_story"
    return API_SOURCES.get(api_nome, API_SOURCES[DEFAULT_API])


def buscar_produtos(api_nome=None):
    """Busca produtos de APIs suportadas e formata os dados"""
    if api_nome is None:
        api_nome = session.get("api_selecionada", DEFAULT_API)

    api_url = obter_api_url(api_nome)

    try:
        r = requests.get(api_url, timeout=15)
        r.raise_for_status()
        dados = r.json()

        produtos = []

        # DummyJSON fornece `products` como dicionário
        if api_nome == "dummyjson":
            iterador = dados.get("products", [])
        else:
            # FakeStore é lista simples
            iterador = dados if isinstance(dados, list) else []

        for p in iterador:
            if api_nome == "dummyjson":
                valor_preco = p.get("price", 0)
                valor_original = valor_preco / (1 - p.get("discountPercentage", 0)/100) if p.get("discountPercentage") else valor_preco
                nota = p.get("rating", 0)
                imagem = p.get("thumbnail", "")
                marca = p.get("brand", "N/A")
            else:
                valor_preco = p.get("price", 0)
                valor_original = valor_preco
                rating = p.get("rating", {})
                nota = rating.get("rate", 0) if isinstance(rating, dict) else 0
                imagem = p.get("image", "")
                marca = p.get("brand", "N/A")

            produtos.append({
                "id": p.get("id"),
                "nome": p.get("title", "Produto"),
                "preco": round(valor_preco, 2),
                "preco_original": round(valor_original, 2),
                "imagem": imagem,
                "categoria": p.get("category", "Outros"),
                "desconto": round(p.get("discountPercentage", 0) if api_nome == "dummyjson" else 0, 1),
                "descricao": p.get("description", ""),
                "marca": marca,
                "avaliacao": round(nota, 1)
            })

        return produtos

    except Exception as e:
        print(f"Erro ao buscar produtos de {api_nome} ({api_url}): {e}")
        # Tenta fallback para API padrão se a API selecionada falhar
        if api_nome != DEFAULT_API:
            print(f"Tentando fallback para {DEFAULT_API}...")
            return buscar_produtos(DEFAULT_API)
        return []


def enviar_email(destino, assunto, corpo):
    if not EMAIL_PASSWORD or EMAIL_PASSWORD.strip() == "":
        aviso = "EMAIL_PASSWORD não configurado; email não enviado."
        print(aviso)
        return False

    msg = EmailMessage()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = destino
    msg["Subject"] = assunto
    msg.set_content(corpo)

    context = ssl.create_default_context()
    try:
        if EMAIL_PORT == 465:
            with smtplib.SMTP_SSL(EMAIL_HOST, EMAIL_PORT, timeout=30, context=context) as server:
                server.set_debuglevel(1)
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=30) as server:
                server.set_debuglevel(1)
                if EMAIL_USE_TLS:
                    server.starttls(context=context)
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(msg)

        print(f"Email enviado para {destino}")
        return True
    except Exception as e:
        print(f"Falha ao enviar email para {destino}: {type(e).__name__}: {e}")
        return False


def buscar_categorias(produtos):
    """Extrai categorias únicas dos produtos"""
    categorias = set()
    for p in produtos:
        categorias.add(p["categoria"])
    return sorted(list(categorias))


def filtrar_produtos(produtos, busca=None, categoria=None, min_preco=None, max_preco=None, ordenar=None):
    """Filtra produtos com base nos parâmetros"""
    resultados = produtos.copy()
    
    # Filtro por busca
    if busca:
        busca = busca.lower()
        resultados = [p for p in resultados if busca in p["nome"].lower() or busca in p["categoria"].lower()]
    
    # Filtro por categoria
    if categoria and categoria != "todas":
        resultados = [p for p in resultados if p["categoria"] == categoria]
    
    # Filtro por preço
    if min_preco:
        resultados = [p for p in resultados if p["preco"] >= float(min_preco)]
    if max_preco:
        resultados = [p for p in resultados if p["preco"] <= float(max_preco)]
    
    # Ordenação
    if ordenar:
        if ordenar == "menor_preco":
            resultados.sort(key=lambda x: x["preco"])
        elif ordenar == "maior_preco":
            resultados.sort(key=lambda x: x["preco"], reverse=True)
        elif ordenar == "maior_desconto":
            resultados.sort(key=lambda x: x["desconto"], reverse=True)
        elif ordenar == "avaliacao":
            resultados.sort(key=lambda x: x["avaliacao"], reverse=True)
    
    return resultados


def buscar_produto_por_id(id_produto, api_nome=None):
    """Busca um produto específico pelo ID"""
    produtos = buscar_produtos(api_nome)
    return next((p for p in produtos if p["id"] == id_produto), None)


@app.context_processor
def carrinho_info():
    """Contexto global para o badge do carrinho"""
    carrinho = session.get("carrinho", [])
    total = sum(p.get("qtd", 1) for p in carrinho)
    return dict(total_carrinho=total)


@app.context_processor
def api_info():
    return dict(api_selecionada=session.get("api_selecionada", DEFAULT_API))


@app.route("/")
def index():
    """Página inicial com todos os produtos e filtros"""
    api_selecionada = request.args.get("api", session.get("api_selecionada", DEFAULT_API))
    if api_selecionada not in API_SOURCES:
        api_selecionada = DEFAULT_API

    session["api_selecionada"] = api_selecionada

    produtos = buscar_produtos(api_selecionada)
    
    # Obtém parâmetros de filtro da URL
    busca = request.args.get("busca", "")
    categoria = request.args.get("categoria", "todas")
    min_preco = request.args.get("min_preco")
    max_preco = request.args.get("max_preco")
    ordenar = request.args.get("ordenar")
    
    # Aplica filtros
    produtos_filtrados = filtrar_produtos(produtos, busca, categoria, min_preco, max_preco, ordenar)
    
    # Adiciona informações de favoritos
    favoritos = session.get("favoritos", [])
    for p in produtos_filtrados:
        p["favoritado"] = p["id"] in favoritos
    
    # Obtém categorias únicas
    categorias = buscar_categorias(produtos)
    
    return render_template(
        "index.html",
        produtos=produtos_filtrados,
        categorias=categorias,
        busca=busca,
        categoria_selecionada=categoria,
        min_preco=min_preco,
        max_preco=max_preco,
        ordenar=ordenar,
        api_selecionada=api_selecionada
    )


@app.route("/trocar_api/<api_nome>")
def trocar_api(api_nome):
    if api_nome not in API_SOURCES:
        flash("API desconhecida, selecionando padrão.", "warning")
        api_nome = DEFAULT_API

    session["api_selecionada"] = api_nome
    return redirect(url_for("index", api=api_nome))


@app.route("/produto/<int:id>")
def produto_detalhe(id):
    """Página de detalhes do produto"""
    api_selecionada = session.get("api_selecionada", DEFAULT_API)
    produto = buscar_produto_por_id(id, api_selecionada)
    if not produto:
        return redirect(url_for('index'))
    
    favoritos = session.get("favoritos", [])
    produto["favoritado"] = id in favoritos
    
    return render_template("produto.html", produto=produto)


@app.route("/add_carrinho/<int:id>")
def add_carrinho(id):
    """Adiciona produto ao carrinho (com reload)"""
    produto = buscar_produto_por_id(id)
    
    if produto:
        carrinho = session.get("carrinho", [])
        
        for item in carrinho:
            if item["id"] == produto["id"]:
                item["qtd"] = item.get("qtd", 1) + 1
                break
        else:
            produto_copy = produto.copy()
            produto_copy["qtd"] = 1
            carrinho.append(produto_copy)
        
        session["carrinho"] = carrinho
        session.modified = True
    
    return redirect(request.referrer or url_for('index'))


@app.route("/add_ajax/<int:id>", methods=["POST"])
def add_ajax(id):
    """Adiciona produto ao carrinho via AJAX (sem reload)"""
    produto = buscar_produto_por_id(id)
    
    if produto:
        carrinho = session.get("carrinho", [])
        
        for item in carrinho:
            if item["id"] == produto["id"]:
                item["qtd"] = item.get("qtd", 1) + 1
                break
        else:
            produto_copy = produto.copy()
            produto_copy["qtd"] = 1
            carrinho.append(produto_copy)
        
        session["carrinho"] = carrinho
        session.modified = True
    
    total = sum(p.get("qtd", 1) for p in session.get("carrinho", []))
    return jsonify({"total": total})


@app.route("/carrinho")
def carrinho():
    """Página do carrinho"""
    carrinho = session.get("carrinho", [])
    total = sum(item["preco"] * item["qtd"] for item in carrinho)
    return render_template("carrinho.html", carrinho=carrinho, total=round(total, 2))


@app.route("/carrinho_json")
def carrinho_json():
    """Retorna o carrinho em JSON para o carrinho lateral"""
    return jsonify(session.get("carrinho", []))


@app.route("/remover/<int:id>")
def remover_do_carrinho(id):
    """Remove um item do carrinho"""
    carrinho = session.get("carrinho", [])
    carrinho = [item for item in carrinho if item["id"] != id]
    session["carrinho"] = carrinho
    session.modified = True
    return redirect(url_for('carrinho'))


@app.route("/favorito/<int:id>")
def favorito(id):
    """Gerencia favoritos via AJAX"""
    favoritos = session.get("favoritos", [])
    
    if id in favoritos:
        favoritos.remove(id)
        status = "remove"
    else:
        favoritos.append(id)
        status = "add"
    
    session["favoritos"] = favoritos
    return jsonify({"status": status})


@app.route("/favoritos_status")
def favoritos_status():
    """Retorna lista de IDs favoritados para o frontend"""
    return jsonify(session.get("favoritos", []))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Página de login"""
    proxima = request.args.get("proxima")
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        if email and senha:
            codigo = gerar_codigo()
            session["usuario"] = {"email": email, "nome": email.split("@")[0], "codigo": codigo}

            # Envia email de boas-vindas e notificação interna
            corpo_usuario = (
                f"Olá {session['usuario']['nome']},\n\n"
                "Muito obrigado por entrar na GoldenClick! "
                "Seu login foi efetuado com sucesso e você já pode continuar suas compras.\n\n"
                "Abraços,\nEquipe GoldenClick"
            )
            ok_usuario = enviar_email(email, "Bem-vindo à GoldenClick", corpo_usuario)

            corpo_golden = (
                f"Novo login de usuário:\n"
                f"Nome: {session['usuario']['nome']}\n"
                f"Email: {email}\n"
                f"Código: {codigo}\n"
            )
            ok_interno = enviar_email(EMAIL_ADDRESS, "GoldenClick: usuário logou", corpo_golden)

            if ok_usuario and ok_interno:
                flash("Login realizado e emails enviados com sucesso.", "success")
            else:
                flash("Login realizado, mas houve problema ao enviar notificações por email.", "warning")

            return redirect(url_for(proxima or 'index'))

    return render_template("login.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    """Página de cadastro"""
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        senha = request.form.get("senha")

        if nome and email and senha:
            codigo = gerar_codigo()
            session["usuario"] = {"email": email, "nome": nome, "codigo": codigo}

            # Notificação para o usuário
            corpo_usuario = (
                f"Olá {nome},\n\n"
                "Seu cadastro foi realizado com sucesso na GoldenClick. "
                "Muito obrigado por escolher a nossa plataforma!\n\n"
                f"Seu código do usuário é: {codigo}\n"
                "Estamos animados em te atender!\n\n"
                "Atenciosamente,\nEquipe GoldenClick"
            )
            ok_usuario = enviar_email(email, "Bem-vindo(a) à GoldenClick", corpo_usuario)

            # Notificação interna
            corpo_golden = (
                f"Novo cadastro de usuário:\n"
                f"Nome: {nome}\n"
                f"Email: {email}\n"
                f"Código: {codigo}\n"
                f"Requisito: nome, email e senha fornecidos\n"
            )
            ok_interno = enviar_email(EMAIL_ADDRESS, "GoldenClick: novo cadastro", corpo_golden)

            if ok_usuario and ok_interno:
                flash("Cadastro realizado e emails enviados com sucesso.", "success")
            else:
                flash("Cadastro realizado, mas houve problema ao enviar emails.", "warning")

            return redirect(url_for('index'))

    return render_template("cadastro.html")


@app.route("/logout")
def logout():
    """Faz logout do usuário"""
    session.clear()
    return redirect(url_for('index'))


@app.route("/trocar_conta")
def trocar_conta():
    """Troca de conta: faz logout e redireciona para login"""
    session.clear()
    return redirect(url_for('login'))


@app.route("/favoritos")
def favoritos():
    """Página de produtos favoritados"""
    produtos = buscar_produtos()
    favoritos_ids = session.get("favoritos", [])
    produtos_favoritos = [p for p in produtos if p["id"] in favoritos_ids]
    return render_template("favoritos.html", produtos=produtos_favoritos)


@app.route("/finalizar")
def finalizar():
    """Finaliza a compra"""
    if "usuario" not in session:
        return redirect(url_for('login', proxima='finalizar'))

    carrinho = session.get("carrinho", [])
    if not carrinho:
        return redirect(url_for('carrinho'))

    itens = []
    total = 0
    for item in carrinho:
        subtotal = item["preco"] * item["qtd"]
        total += subtotal
        itens.append({
            "nome": item["nome"],
            "imagem": item["imagem"],
            "quantidade": item["qtd"],
            "preco": item["preco"],
            "subtotal": round(subtotal, 2)
        })

    usuario = session["usuario"]
    codigo_usuario = usuario.get("codigo", gerar_codigo())
    usuario["codigo"] = codigo_usuario
    session["usuario"] = usuario
    codigo_pedido = gerar_codigo() #novo codigo para reciclar o mesmo codigo do usuario em cada pedido, para facilitar o restreamento de pedidos 

    # Email para usuário
    itens_descricao = "\n".join([f"- {i['nome']} (x{i['quantidade']}) -> R$ {i['subtotal']:.2f}" for i in itens])
    corpo_usuario = (
        f"Olá {usuario['nome']},\n\n"
        "Sua compra foi finalizada com sucesso!\n"
        f"Código do pedido: {codigo_pedido}\n"
        "Produtos comprados:\n"
        f"{itens_descricao}\n\n"
        f"Total pago: R$ {total:.2f}\n\n"
        "Muito obrigado por confiar na GoldenClick!\n"
        "Estamos felizes em te atender.\n\n"
        "Atenciosamente,\nEquipe GoldenClick"
    )

    # Email interno
    corpo_golden = (
        f"Compra finalizada:\n"
        f"Código do pedido: {codigo_pedido}\n"
        f"Usuário: {usuario['nome']}\n"
        f"Email: {usuario['email']}\n"
        f"Código do usuário: {codigo_usuario}\n"
        f"Produtos: {len(itens)}\n"
        f"Total: R$ {total:.2f}\n"
        f"Detalhes:\n{itens_descricao}\n"
    )
    ok_usuario = enviar_email(usuario["email"], "Compra concluída - GoldenClick", corpo_usuario)
    ok_interno = enviar_email(EMAIL_ADDRESS, "GoldenClick: pedido finalizado", corpo_golden)

    if ok_usuario and ok_interno:
        flash("Compra finalizada e emails enviados com sucesso.", "success")
    elif ok_usuario:
        flash("Compra finalizada. Email enviado para você, mas houve problema no email interno.", "warning")
    elif ok_interno:
        flash("Compra finalizada. Email interno enviado, mas houve problema no email para você.", "warning")
    else:
        flash("Compra finalizada, mas houve problema ao enviar emails de confirmação.", "warning")

    # limpa carrinho e redireciona para página de finalizar
    session["carrinho"] = []
    session.modified = True

    return render_template("finalizar.html", itens=itens, total=round(total, 2))

@app.route("/limpar_carrinho", methods=["POST"])
def limpar_carrinho():
    """Limpa todo o carrinho"""
    session["carrinho"] = []
    session.modified = True
    return jsonify({"status": "success", "total": 0})

@app.route("/remover_ajax/<int:id>", methods=["POST"])
def remover_ajax(id):
    """Remove um item do carrinho via AJAX"""
    carrinho = session.get("carrinho", [])
    carrinho = [item for item in carrinho if item["id"] != id]
    session["carrinho"] = carrinho
    session.modified = True
    
    total = sum(p.get("qtd", 1) for p in session.get("carrinho", []))
    return jsonify({"status": "success", "total": total})


@app.route("/atualizar_quantidade/<int:id>/<int:quantidade>", methods=["POST"])
def atualizar_quantidade(id, quantidade):
    """Atualiza a quantidade de um item no carrinho"""
    carrinho = session.get("carrinho", [])
    
    if quantidade <= 0:
        # Remove o item se quantidade for <= 0
        carrinho = [item for item in carrinho if item["id"] != id]
    else:
        # Atualiza a quantidade
        for item in carrinho:
            if item["id"] == id:
                item["qtd"] = quantidade
                break
    
    session["carrinho"] = carrinho
    session.modified = True
    
    total = sum(p.get("qtd", 1) for p in session.get("carrinho", []))
    return jsonify({"status": "success", "total": total})


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)