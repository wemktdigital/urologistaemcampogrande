# Marcelino Ibrahim

Cópia estática de [urologistaemcampogrande.com.br](https://urologistaemcampogrande.com.br/) em Astro.

O WordPress no servidor não é alterado por este repositório. As páginas públicas foram espelhadas com os mesmos caminhos. Onde o shortcode `[page_title]` aparecia sem ser processado, a cópia usa o título da página.

`scripts/audit.py` compara cada página da cópia com o site oficial e lista arquivos locais que faltam.

```sh
npm install
npm run build
npm run preview
```
