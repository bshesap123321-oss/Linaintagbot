# 🎿 AI İçerik Botu: kar maskesi markası için

Her gün **kendi kendine** fotoğraf ya da Reels videosu üretip Instagram'da paylaşan bot.
Sizin ürünlerinizi, sizin karakter kadronuz (Lina, Ahmet, Mehmet, Zeynep...) takar; kayakta,
telesiyejde, pist başında komik anlar yaşarlar. Bilgisayarınız kapalıyken de çalışır.

```
 Planlayıcı ─► Fikir ajanı ─► Prompt ajanı ─► Görsel ajanı ─► Kontrol ─► (Video ajanı ─► Kontrol) ─► Açıklama ─► Instagram
 (bugün hangi   (komik an)     (yüzler ve      (Gemini)       (ürün,     (Veo, 8 sn dikey)               (marka dili,  (AI etiketiyle)
  ürün, sahne,                  maske birebir)                 yüz, el)                                   fiyat, DM)
  kimler?)
```

## Neler yapar?
- **Adil sırayla döner:** En uzun süredir paylaşılmayan ürünü ve karakterleri seçer, dünkü sahneyi tekrar etmez.
- **Ürününüz birebir çıkar:** Ürün fotoğraflarınız her görselde referans olarak kullanılır. Kontrol ajanı maske farklı çizildiyse görseli reddeder.
- **Yüzler tutarlı kalır:** Her karakterin sabit tarifi ve referans fotoğrafı her seferinde kullanılır.
- **Fotoğraf ve Reels:** `brand.yaml` dosyasındaki oranlara göre bazen fotoğraf, bazen 8 saniyelik dikey video paylaşır.
- **Kötü içerik paylaşmaz:** Ayrı bir ajan her görseli ve videoyu puanlar, beğenmezse düzeltme talimatıyla yeniden ürettirir. Hiçbiri geçmezse o gün paylaşım yapmaz.
- **Satış odaklı açıklama:** Komik bir açılış cümlesi, ürün adı, fiyat ve bedenler, "DM'den MASKE yazın" çağrısı ve hashtag'ler.
- **Şeffaf:** Instagram'ın resmi "Yapay zekâ bilgisi" etiketini otomatik ekler.
- **Başka markaya uyarlanabilir:** `brand.yaml`, `cast/` ve `products/` değişir, kod değişmez.

---

## Kurulum (bir kez)

### 1. GitHub ayarları
- **Settings → Actions → General → Workflow permissions** altında **Read and write permissions** seç ve kaydet.
- **Settings → Pages → Build and deployment → Source** altında **GitHub Actions** seç. Fotoğraf ve videolar Instagram'a buradan gider. Depo **Public** olmalı.

### 2. Anahtarlar
**Settings → Secrets and variables → Actions → New repository secret:**

| Ad (birebir) | Nereden |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) → Get API key. Görsel ve video için faturalandırmayı açın |
| `IG_ACCESS_TOKEN` | Aşağıdaki "Instagram token" adımları |
| `IG_USER_ID` | İsteğe bağlı, boş bırakılırsa otomatik bulunur |
| `GH_PAT` | Önerilir: token'ın her ay otomatik yenilenmesi için (aşağıda) |

**Instagram token:**
1. Instagram hesabınızın **Profesyonel hesap** (İşletme veya İçerik üreticisi) olduğundan emin olun.
2. [developers.facebook.com](https://developers.facebook.com) adresinde **Uygulama oluştur** deyin ve türü **İşletme** seçin.
3. **Instagram** ürününü ekleyin ve **API setup with Instagram login** bölümünü açın.
4. **Add account** ile hesabınızı bağlayın, ardından **Generate token** ile token üretin. Token 60 gün geçerlidir.

**GH_PAT:** GitHub'da **Settings → Developer settings → Fine-grained tokens** yolunu izleyin. Sadece bu depoyu seçin, **Secrets: Read and write** iznini verin, süreyi 1 yıl yapın.

### 3. Ürünlerinizi ekleyin
Her ürün için `products/` altında bir klasör açın, örneğin `products/biyikli-amca/`:
- `product.yaml`: ad, görsel tarif, fiyat, bedenler (örnek dosyalar hazır, kendi bilgilerinizle değiştirin)
- **1-3 ürün fotoğrafı:** Düz zemin, gün ışığı, önden çekilmiş; mümkünse biri bir kafaya takılı halde. *En önemli adım budur.*

Satışta olmayan bir ürün için `active: false` yazmanız yeterli.

### 4. Karakter fotoğrafları
Her karakter için `cast/<isim>/` klasörüne 1-2 referans fotoğrafı koyun. Gemini uygulamasında aşağıdaki gibi bir prompt ile üretebilirsiniz:
```
Photorealistic studio portrait of [brand.yaml'daki appearance satırı]. Front-facing,
neutral expression, plain light grey background, soft even light, 85mm lens.
```
Fotoğraf koymazsanız bot yine çalışır ama yüzler her gün biraz farklı çıkar. Maskeli sahnelerde bu pek belli olmaz.

### 5. İlk deneme
1. **Actions → Günlük paylaşım → Run workflow** yolunu izleyin. **Deneme modu** kutusunu işaretleyin, türü seçin ve çalıştırın.
2. Bitince çalışmaya tıklayın. Özette plan, puanlar ve açıklama görünür; dosyalar `posts/` klasöründedir.
3. Beğendiyseniz kutuyu işaretlemeden çalıştırın. **İlk paylaşım yapılır** 🎉

Bundan sonra bot her gün **19:00'da (TR)** kendisi paylaşır.

---

## Özelleştirme (`brand.yaml`)

| Ne istiyorsunuz? | Nereyi değiştirin? |
|---|---|
| Yeni karakter | `cast:` listesine ekleyin ve `cast/<id>/` klasörü açın |
| Yeni sahne | `scenes:` listesine ekleyin; `people: [2, 3]` sahnede kaç kişi olacağını belirler |
| Daha çok video | `formats:` örneğin `image: 1, reel: 2` |
| Marka dili, satış cümlesi | `voice`, `call_to_action` |
| Paylaşım saati | `.github/workflows/daily-post.yml` → `cron` (saat UTC'dir, TR = UTC+3) |
| Kalite eşiği | `review.min_score` |

## Maliyet ve süre
- Fotoğraf gönderisi: birkaç dakika, düşük maliyet.
- Reels: 5-15 dakika. Veo video üretimi görsele göre belirgin şekilde daha pahalıdır. Güncel fiyat için Google'ın Gemini API fiyat sayfasına bakın.
  Maliyeti düşürmek için `formats.reel` değerini azaltın ya da `GEMINI_VIDEO_MODEL` değişkenine daha ucuz bir Veo modeli yazın.

## Sorun giderme

| Hata | Çözüm |
|---|---|
| `Eksik ayar: GEMINI_API_KEY` | Secret adını kontrol edin: büyük harf, noktasız I |
| `Dosyaya 10 dakikada ulaşılamadı` | Depo Public mi? **Settings → Pages → Source = GitHub Actions** seçili mi? |
| `Instagram API hatası ... kod 190` | Token süresi dolmuş. Yenisini alın ve `GH_PAT` ekleyin |
| `kaliteli görsel çıkmadı` | Bot o gün paylaşmadı. Ürün fotoğraflarını iyileştirin ya da `min_score` değerini 6 yapın |
| Gemini `429` | Faturalandırma açık mı? |

Bilgisayarda test etmek için:
```bash
pip install -r requirements.txt pytest
python -m pytest -q                                   # testler (internet gerekmez)
GEMINI_API_KEY=... DRY_RUN=true python -m influencer_bot check
```

## Dikkat
- Başka markaların adlarını veya logolarını (örneğin LEGO) ürün adında, açıklamada ya da görselde kullanmayın. Bot görsellerde bunu zaten engeller.
- Ücretli reklamlarda sigara görseli Meta'nın reklam kurallarına takılabilir.
- Takipçi satın almak ya da otomatik beğeni/takip yapmak hesabın kapanmasına yol açabilir. Bu bot sadece içerik paylaşır.
