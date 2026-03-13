<div align="center">

<img src="docs/assets/Eneo-logo-svg.svg" alt="Eneo Logo" width="400"/> 

# Eneo

**Democratic AI Platform for the Public Sector**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Made for: Public Sector](https://img.shields.io/badge/Made%20for-Public%20Sector-green)](https://github.com/eneo-ai/eneo)
[![Contributions Welcome](https://img.shields.io/badge/Contributions-Welcome-brightgreen.svg)](#contributing)
[![Contributors](https://img.shields.io/github/contributors/eneo-ai/eneo)](https://github.com/eneo-ai/eneo/graphs/contributors)

[🌐 Website](https://eneo.ai/) • [Getting Started](#-getting-started) • [Features](#-key-features) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## 🏛️ What is Eneo?

Eneo is an open-source AI platform designed for Swedish public sector organizations to deploy and manage AI assistants while maintaining complete control over data, security, and algorithms. 

Originally developed by Sundsvall Municipality and Ånge Municipality, Eneo embodies the principle that **"Generative AI must not be a technology for the few, but a technology for everyone."**

### Why Choose Eneo?

- **🔒 Data Sovereignty** - Your data never leaves your environment
- **🤝 Model Agnostic** - Use OpenAI, Anthropic, Azure, or local models
- **🏛️ Public Sector Focus** - Built for municipal and government needs
- **📋 Compliance Ready** - GDPR and EU AI Act support built-in
- **🔓 True Open Source** - AGPL v3 licensed with no vendor lock-in

---

## ✨ Key Features

- **AI Assistant Management** - Create and customize assistants for specific organizational needs
- **Collaborative Spaces** - Team workspaces with role-based access control
- **Knowledge Management** - Process documents, crawl websites with optional HTTP auth, semantic search
- **Real-time Chat** - Streaming responses with background task processing and token tracking
- **Multi-language** - Swedish and English interface with seamless switching
- **Multi-Tenant Federation** - Per-tenant identity providers with encrypted configuration
- **Tenant-Specific Credentials** - Isolated LLM API keys per organization with Fernet encryption
- **API First** - Full API documentation, type-safe integration, and runtime observability

---

## 🚀 Getting Started

### For Production Deployment

Deploy Eneo in your organization with Docker Compose:

```bash
# Clone and navigate to deployment files
git clone https://github.com/eneo-ai/eneo.git
cd eneo/docs/deployment/

# Configure and deploy
cp env_backend.template env_backend.env
cp env_frontend.template env_frontend.env
# ... configure your environment ...
docker compose up -d
```

> **Note:** The provided Docker Compose configuration is a reference example. Customize it for your organization's security, networking, and infrastructure requirements.

📖 **[Full Production Guide →](docs/DEPLOYMENT.md)**

### For Developers

Set up your development environment with VS Code DevContainer:

```bash
git clone https://github.com/eneo-ai/eneo.git
cd eneo && code .
# Click "Reopen in Container" when prompted
```

- **Platform**: http://localhost:3000
- **API Docs**: http://localhost:8123/docs
- **Default Login**: `user@example.com` / `Password1!`

📖 **[Development Setup Guide →](docs/INSTALLATION.md)**

---

## 🖼️ Platform Preview

<div align="center">
<img src="docs/assets/eneo_startpage.png" alt="Eneo Personal Assistant Interface" width="700"/>
<p><em>Personal AI Assistant Interface</em></p>
</div>

<div align="center">
<img src="docs/assets/eneo_space.png" alt="Eneo Collaborative Spaces" width="700"/>
<p><em>Team Collaboration Spaces</em></p>
</div>

---

## 🏗️ Architecture

Modern microservices architecture with clean separation of concerns:

- **Frontend**: SvelteKit, TypeScript, Tailwind CSS
- **Backend**: FastAPI (Python 3.11+), SQLAlchemy
- **Database**: PostgreSQL with pgvector
- **Cache/Queue**: Redis with ARQ workers
- **Deployment**: Docker Compose with Traefik

<details>
<summary>View Architecture Diagram</summary>
<img src="docs/assets/eneo_architecture.png" alt="Eneo Architecture" width="700"/>
</details>

---

## 📚 Documentation

| Guide | Description |
|-------|-------------|
| **[Installation](docs/INSTALLATION.md)** | Development environment setup |
| **[Deployment](docs/DEPLOYMENT.md)** | Production deployment with Docker Compose |
| **[Architecture](docs/ARCHITECTURE.md)** | Technical architecture and design patterns |
| **[Multi-Tenant Setup](docs/MULTITENANT_OIDC_SETUP_GUIDE.md)** | Per-tenant identity provider configuration |
| **[AI Providers](https://docs.eneo.ai/guides/ai-providers)** | Provider configuration & credential management |
| **[Contributing](docs/CONTRIBUTING.md)** | Contribution guidelines |
| **[Security](docs/SECURITY.md)** | Security practices and compliance |
| **[Troubleshooting](docs/TROUBLESHOOTING.md)** | Common issues and solutions |

---

## 🤝 Contributing

We welcome contributions from municipalities, organizations, and developers who share our vision of democratic AI.

### Quick Start

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

See our **[Contributing Guide](docs/CONTRIBUTING.md)** for detailed guidelines.

---

## 🏛️ Community & Governance

### Democratic Control

Eneo is governed by a user association of public sector organizations, ensuring development priorities align with public interest rather than commercial goals.

### Get Involved

- **Public Sector Organizations**: Contact `digitalisering@sundsvall.se` for collaboration
- **Developers**: Join our [GitHub Discussions](https://github.com/eneo-ai/eneo/discussions)
- **Bug Reports**: Submit via [GitHub Issues](https://github.com/eneo-ai/eneo/issues)
- **Website**: https://eneo.ai/
- **Forum**: https://forum.eneo.ai/ (requires government or municipality email)
- **Chat**: https://chat.eneo.ai/ (requires government or municipality email)

---

## 🙏 Acknowledgments

**Developed by**: Sundsvall Municipality & Ånge Municipality, Sweden 🇸🇪

**Inspired by**: [Open ePlatform](https://www.openeplatform.org/) - Successfully used by 200+ Swedish municipalities since 2010

**Special Thanks**: InooLabs AB (now Intric AB) for foundational contributions

---

## 📜 License

```
Eneo - Democratic AI Platform for the Public Sector
Copyright (C) 2023-2025 Sundsvall Municipality & Ånge Municipality

Licensed under GNU Affero General Public License v3.0
```

See [LICENSE](LICENSE) for full license text.

---

<div align="center">

**Made with ❤️ by the Swedish Public Sector for the Global Community**

*Empowering democratic access to AI technology*

[🌐 Website](https://eneo.ai/) • [🫱🏻‍🫲🏽 Forum](https://forum.eneo.ai/) • [💬 Chat](https://chat.eneo.ai/) • [📧 Contact](mailto:digitalisering@sundsvall.se) • [💬 Discussions](https://github.com/eneo-ai/eneo/discussions) • [🐛 Issues](https://github.com/eneo-ai/eneo/issues)
<br/>
<sub>Forum and Chat require a government or municipality email.</sub>

</div>

---

## 🚀 Development Branch

This branch contains the latest development features and CI/CD enhancements.
Used for testing new features before merging to production.