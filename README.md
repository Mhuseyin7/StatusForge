# StatusForge

> Self-hosted uptime monitoring, incident management ve public status page platformu.

**StatusForge**, websites, APIs, infrastructure endpoints ve scheduled jobs için bağımsız bir reliability platformudur. Servislerini kendi sunucunda izlemeni, kesintileri yönetmeni ve kullanıcılarına güvenilir bir public status page sunmanı hedefler.

Bu proje açık kaynaklıdır ve **[muhammedkoca.com.tr](https://muhammedkoca.com.tr)** tarafından geliştirilmiştir.

## İçindekiler

- [Öne çıkanlar](#öne-çıkanlar)
- [Mimari](#mimari)
- [Hızlı başlangıç](#hızlı-başlangıç)
- [Konfigürasyon](#konfigürasyon)
- [Geliştirme](#geliştirme)
- [API](#api)
- [Güvenlik](#güvenlik)
- [Katkı](#katkı)
- [Lisans](#lisans)

## Öne çıkanlar

- **Self-hosted deployment:** Docker Compose ile kendi infrastructure’ında çalışır.
- **Monitor engine:** HTTP/HTTPS, TCP ve heartbeat kontrolleri için background worker altyapısı sunar; genişletilebilir monitor modelinde DNS, SSL, domain, JSON/API, keyword ve ping türleri de bulunur.
- **Incident lifecycle:** Tek bir geçici hatada alarm üretmemek için configurable failure/recovery confirmation kullanır.
- **Multi-tenant access:** Organization, member role ve tenant isolation yaklaşımıyla ekip kullanımına uygundur.
- **Security first:** Argon2id password hashing, rotating refresh sessions, API-key hashing, audit logging ve SSRF koruması içerir.
- **Operations dashboard:** Responsive, dark/light theme destekli developer-focused dashboard arayüzü vardır.
- **Open API:** REST API, OpenAPI schema ve interaktif documentation sağlar.

## Mimari

```text
Next.js web application
          │
          ▼
FastAPI REST API ─── PostgreSQL (source of truth)
          │
          ▼
Redis queue / locks
          │
          ▼
Celery scheduler → Celery workers → monitor checks → incidents
```

| Katman | Teknoloji | Sorumluluk |
| --- | --- | --- |
| Web | Next.js, React, TypeScript | Dashboard ve kullanıcı deneyimi |
| API | FastAPI, Pydantic, SQLAlchemy | Authentication, RBAC, REST API |
| Worker | Celery, Redis | Scheduled monitor execution |
| Data | PostgreSQL, Alembic | Kalıcı data ve schema migration |
| Deployment | Docker Compose | Local ve self-hosted çalışma ortamı |

## Hızlı başlangıç

### Gereksinimler

- Docker Desktop veya Docker Engine with Compose plugin
- En az 2 GB RAM önerilir
- Kullanılabilir `3000` ve `8000` portları

### Kurulum

Repository’yi clone ettikten sonra environment file’ı oluştur:

```bash
cp .env.example .env
```

Windows PowerShell için:

```powershell
Copy-Item .env.example .env
```

`.env` dosyasındaki `SECRET_KEY` değerini production kullanımı öncesinde güçlü, rastgele bir değerle değiştir. Örneğin:

```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))
```

Servisleri başlat:

```bash
docker compose up -d --build
```

Uygulama hazır olduğunda aşağıdaki adresleri açabilirsin:

| Adres | Açıklama |
| --- | --- |
| `http://localhost:3000` | StatusForge web dashboard |
| `http://localhost:8000/docs` | Interaktif API documentation |
| `http://localhost:8000/health` | Process health endpoint |
| `http://localhost:8000/ready` | Dependency readiness endpoint |

Logları takip etmek için:

```bash
docker compose logs -f api worker scheduler web
```

Servisleri durdurmak için:

```bash
docker compose down
```

## Konfigürasyon

Tüm environment values `.env.example` içinde açıklanmış default değerlerle gelir. Production ortamında en az şu değerleri değiştir:

| Variable | Açıklama |
| --- | --- |
| `SECRET_KEY` | JWT signing için en az 32 karakterlik gizli key |
| `POSTGRES_PASSWORD` | PostgreSQL kullanıcı parolası |
| `DATABASE_URL` | PostgreSQL connection URL |
| `REDIS_URL` | Redis connection URL |
| `APP_URL` | Public web URL |
| `API_URL` | Public API URL |
| `CORS_ORIGINS` | İzin verilen web origin listesi |
| `ALLOW_PRIVATE_MONITORS` | Private network monitor iznini açar; default `false` |

> `ALLOW_PRIVATE_MONITORS=true` yalnızca izole edilmiş ve güvenilen ağlarda kullanılmalıdır. Bu ayar SSRF koruma sınırlarını genişletir.

## Geliştirme

Development komutları root dizinindeki `Makefile` üzerinden sağlanır:

```bash
make dev       # Docker ile foreground development
make up        # Docker ile background çalışma
make test      # Backend testleri
make lint      # Backend ve frontend linting
make migrate   # Alembic migration çalıştırma
```

Frontend için Node.js 22+, backend için Python 3.12+ gerekir. Docker kullanımı lokal Python/PostgreSQL/Redis kurulumuna ihtiyaç bırakmaz.

```bash
cd apps/web
npm install
npm run lint
npm run test
npm run build
```

## API

API namespace’i `/api/v1` altındadır. Swagger UI üzerinden tüm request/response schema’larını inceleyebilir ve endpoint’leri deneyebilirsin:

```text
http://localhost:8000/docs
```

Temel resource grupları:

- `auth` — register, login, refresh session, logout
- `organizations` — workspace ve membership erişimi
- `monitors` — monitor oluşturma, kontrol kuyruğa alma ve check history
- `api-keys` — scope destekli organization API key yönetimi

API hata cevapları tutarlı bir form kullanır:

```json
{
  "error": {
    "code": "HTTP_404",
    "message": "Monitor not found"
  }
}
```

## Güvenlik

StatusForge güvenliği product architecture’ın temel parçası olarak ele alır:

- Password’ler plaintext olarak saklanmaz; Argon2id ile hashlenir.
- Refresh token’lar database’de yalnızca hash formunda tutulur ve kullanımda rotate edilir.
- API key’in tamamı yalnızca oluşturulurken gösterilir; sonrasında hash saklanır.
- Tenant resource sorguları organization membership doğrulaması yapar.
- HTTP/TCP monitor hedefleri varsayılan olarak localhost, private, loopback, link-local ve metadata ağlarına erişemez.
- API response’larında request ID, güvenli security header’ları ve validation error formatı uygulanır.

Vulnerability bildirimleri için [SECURITY.md](SECURITY.md) dosyasını incele.

## Roadmap

Platformun genişletilebilir domain modeli; status pages, maintenance windows, notification providers, outgoing webhooks, SSL/domain/DNS monitor executors ve gelişmiş analytics gibi reliability capability’leri için tasarlanmıştır. Her yeni capability, test ve güvenlik incelemesiyle birlikte eklenmelidir.

## Katkı

Katkılar memnuniyetle karşılanır. Pull request göndermeden önce:

1. Change’i dar ve açıklayıcı tut.
2. İlgili testleri ekle veya güncelle.
3. `make lint` ve `make test` komutlarını çalıştır.
4. Secret, token veya gerçek production data commit etme.

Detaylı kurallar için [CONTRIBUTING.md](CONTRIBUTING.md) dosyasına bak.

## Lisans

StatusForge, [Apache-2.0](LICENSE) lisansı ile açık kaynak olarak sunulur.

---

Developed with care by [muhammedkoca.com.tr](https://muhammedkoca.com.tr).
