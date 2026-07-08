# Visual Acquisition Technical Research Report
**Forgotten Maritime Disasters AI-Operator**
Date: 2026-07-08 | Research: Visuals Strategy

---

## Executive Summary (VN)

Hệ thống visual acquisition nên dùng **3-tier fallback chain**:
1. **Stock APIs** (Pexels/Pixabay): phần lớn shot công cộng, chi phí 0, reliable
2. **Local SDXL generation** (Apple Silicon): chân dung/bản đồ lịch sử khi stock không có, ~10-40s/img (M1/M2), MLX 40% faster
3. **Cloud fallback** (fal.ai): khi local overload, timeout, hoặc cần quality cao

**Khuyến cáo chính**: Combine Pexels + Pixabay (caching 24h) → local MLX-SDXL (ComfyUI API) → fal.ai Flux (khi deadline gần).

---

## 1. Stock Image APIs Comparison

### 1.1 Pexels API

| Dimension | Detail |
|-----------|--------|
| **Auth** | API key in `Authorization: API-KEY` header |
| **Rate Limit** | 200 req/hr, 20k req/month (free) |
| **Quota Tracking** | `X-Ratelimit-Limit`, `X-Ratelimit-Remaining`, `X-Ratelimit-Reset` headers |
| **License** | CC0 (no attribution required, but appreciated) |
| **Pagination** | Up to 80 items/page, `prev_page`/`next_page` URLs |
| **Search** | `/search` endpoint with query, filters (color, orientation, size) |
| **Formats** | JSON, multiple resolutions (original, large, medium, small, portrait, landscape, tiny) |
| **Videos** | Also supports video search (similar endpoints) |
| **Cost** | Free (can request higher limits by demonstrating attribution) |

**Quota Strategy**: 20k req/month = ~667 req/day → ~28 req/hour average. Sufficient for 3 videos/week (each needs ~5-10 stock searches). **Batch search on schedule, cache 24h.**

### 1.2 Pixabay API

| Dimension | Detail |
|-----------|--------|
| **Auth** | API key in query param `?key=API-KEY` |
| **Rate Limit** | 100 req/60s (no monthly cap, but cache requirement) |
| **Caching** | **MANDATORY: cache 24h** (stated in docs) |
| **License** | Pixabay License (CC0 equivalent, no attribution required) |
| **Max Results** | 500 per query, paginated |
| **Search** | `/` endpoint with `q` (query), `lang`, `order`, `per_page`, `page` |
| **Formats** | JSON with image URLs (preview + full HD) |
| **Categories** | Nature, people, places, food, sports, animals, backgrounds, fashion, etc. |
| **Cost** | Free (unlike Pexels, no monthly cap, only 60s rate limit) |

**Quota Strategy**: 100 req/60s = 6k req/hour potential if unbatched. **Practical: batch searches, cache results.** Cache strategy outweighs rate limit.

### 1.3 Comparison Matrix

| Feature | Pexels | Pixabay |
|---------|--------|---------|
| Monthly quota | 20k (hard cap) | Unlimited (soft 60s limit) |
| Search volume/mo (3 vids/wk) | ✅ Sufficient | ✅ No cap |
| License clarity | CC0 (appreciated) | CC0 (required cache) |
| API stability | Mature | Mature |
| Image quality (avg) | High | High |
| API docs clarity | Excellent | Good |
| Fallback ready | Yes | Yes |

**Recommendation**: Use **both in parallel**. Pexels first (documented, higher quality), Pixabay as fallback.

---

## 2. Local Image Generation (Stable Diffusion SDXL/Flux)

### 2.1 Apple Silicon Options (M1/M2/M3)

#### A. MLX Framework (⭐ BEST FOR M-series)
- **Performance**: 40% faster than PyTorch MPS on M1/M2/M3
- **Memory**: Unified memory model → M1 (8GB) can run SDXL (slow), M1 Pro/Max comfortable, M2/M3 excellent
- **Setup**: Python + MLX library, WWDC 2025 updates for M5+
- **Generation time**: ~10-25 sec/img on M1 Max 24GB, ~30-50s on M1 8GB (SDXL)
- **Cost**: Free, local-only
- **Status**: Active development (Apple maintains)

```python
# Pseudo-code MLX inference
from mlx_sd import StableDiffusionPipeline

pipe = StableDiffusionPipeline.from_pretrained("stabilityai/stable-diffusion-xl-base-1.0")
image = pipe("ancient shipwreck, 19th century, detailed, 8k").images[0]
image.save("output.png")
```

#### B. Diffusers + MPS (PyTorch)
- **Performance**: Standard, MPS + attention slicing ~20% improvement
- **Setup**: `pip install diffusers torch transformers`
- **Memory**: M1 16GB recommended for SDXL without too much slowdown
- **Generation time**: ~30-60s on M1 16GB (SDXL), ~10-20s on M2 Max
- **Cost**: Free
- **Maturity**: Very stable (Hugging Face maintained)

```python
from diffusers import StableDiffusionXLPipeline
import torch

device = "mps"  # Apple Silicon
pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,  # Memory optimization
    use_safetensors=True
)
pipe.to(device)

# Enable attention slicing (20% faster, ~5-10% quality trade-off)
pipe.enable_attention_slicing()

image = pipe("historical maritime disaster, storm, 1800s").images[0]
image.save("disaster.png")
```

#### C. ComfyUI Local Server (Node-based API)
- **Setup**: Node-graph workflow GUI, expose HTTP/WebSocket API
- **API Pattern**: POST `/prompt` with workflow JSON, WebSocket for progress
- **Advantage**: Modular (ControlNet, upscaling, inpainting in one pipeline)
- **Disadvantage**: Heavier (node overhead), slower than direct diffusers for simple tasks
- **Good for**: Complex workflows (upscale after gen, face detail refinement)

```python
# Python → ComfyUI API (async)
import asyncio, aiohttp

async def generate_with_comfyui(prompt: str, seed: int):
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 0]}},
        "4": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 20, "cfg": 7.0, "positive": ["3", 0], ...}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "gen"}}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("http://localhost:8188/prompt", json={"prompt": workflow}) as r:
            return await r.json()
```

### 2.2 Memory & Performance Recommendations

| Scenario | Chip | SDXL Time | Flux Time | Notes |
|----------|------|-----------|-----------|-------|
| Baseline | M1 8GB | ~60-90s (slow) | ❌ OOM | Don't use for prod |
| Comfortable | M1 Pro 16GB | ~30-45s | ~120s (LoRA only) | OK for 1-2 img/min |
| Good | M1 Max 24GB | ~10-20s | ~40-60s (Flux 12B) | 3-4 img/min sustainable |
| Excellent | M2/M3 32GB | ~5-15s | ~20-30s | **Recommended** |

**For 3 videos/week (2-3 generated images per video)**: M1 16GB is minimum. M2/M3 24GB+ is ideal.

### 2.3 Gotchas: Local Generation

| Gotcha | Mitigation |
|--------|-----------|
| **Model download (first run)** | SDXL base = ~6.5GB, takes 5-10 min. Avoid on first-run prod path. Pre-download on setup. |
| **Memory pressure with others** | Browser + VS Code + generation = potential swap. Monitor via Activity Monitor. Set max workers=1. |
| **MPS device errors** | `device not available` → Upgrade to PyTorch 2.1+. Some old diffusers versions unstable on MPS. |
| **Prompt length & quality** | Longer prompts (>100 tokens) slower & sometimes harmful. Keep documentary shots <50 tokens ("ancient shipwreck, detailed, historical"). |
| **LoRA/ControlNet not on M1** | LoRA feasible; ControlNet uses extra memory. Test before production. |
| **Generator seed reproducibility** | Same seed ≠ same image on different torch versions. Don't rely for exact recreation. |

---

## 3. Cloud Image Generation (Fallback Layer)

### 3.1 fal.ai vs Replicate

| Metric | fal.ai | Replicate |
|--------|--------|-----------|
| **Flux Dev (1024×1024)** | ~$0.025 | ~$0.08 |
| **SDXL (1024×1024)** | ~$0.012 | ~$0.035 |
| **Cold start** | <1s | ~2-5s |
| **Models** | 600+ (curated) | 50k+ (community) |
| **Pricing** | Per image/megapixel | Per second GPU time |
| **Speed** | Optimized | Good |
| **Availability** | Very reliable | Reliable |
| **Best for** | Cost-sensitive, speed | Exotic models |

**Recommendation**: **fal.ai primary**, Replicate fallback for niche needs.

### 3.2 fal.ai Integration

```python
import asyncio
import fal_client

async def generate_via_fal(prompt: str, size_multiplier: float = 1.0):
    """
    Fallback to fal.ai when local generation overloaded or timeout.
    size_multiplier: 0.5 (512×512, $0.006) to 1.0 (1024×1024, $0.025)
    """
    result = await fal_client.run_async(
        "fal-ai/flux-pro",
        arguments={
            "prompt": prompt,
            "image_size": {"width": int(1024 * size_multiplier), "height": int(1024 * size_multiplier)},
            "num_images": 1,
            "safety_checker_version": "v0.2.1"  # Enable safety
        }
    )
    return result["images"][0]["url"]  # Direct download URL
```

---

## 4. Integrated Architecture: Shot List → Visuals

### 4.1 Pipeline Flow

```
[Script Text from LLM]
    ↓
[Shot List Generator] (Claude/Gemini: extract visual beats)
    Example: {
        "beat_0": "shipwreck 1912, bow section underwater",
        "beat_1": "historical map North Atlantic 1912",
        "beat_2": "captain portrait 19th century",
        "beat_3": "archive newspaper headline"
    }
    ↓
[Visual Keyword Mapper] (normalize to search queries)
    → Pexels search: "shipwreck underwater wreckage"
    → Pixabay search: "historic map maritime"
    → Gen candidate: "Captain Smith portrait historical 1912" (if not found)
    ↓
[Stock Search (Parallel Pexels + Pixabay)]
    Cache hit? Return cached result.
    Found? Use ✓
    Not found? → Queue for local generation
    ↓
[Local Generation (MLX-SDXL or ComfyUI)]
    Prompt: "Captain Smith portrait, historical, 19th century, detailed, oil painting style"
    Timeout >45s or memory pressure? → Queue for fal.ai
    ✓ Generated? Return image
    ↓
[Cloud Fallback (fal.ai)]
    Last resort: Flux Pro ($0.025/img)
    ✓ Returned? Use and log cost
    ↓
[License & Attribution Layer]
    Stock: Extract photographer/source (optional for YouTube, but log)
    Generated: Tag as "AI-generated" (per compliance)
    ↓
[Video Assembly]
    Shot + Audio → FFmpeg compose
```

### 4.2 Code Pattern: Resilient Visual Fetcher

```python
# visual_fetcher.py
import asyncio
import time
from typing import Optional
from dataclasses import dataclass
from enum import Enum

class VisualSource(Enum):
    PEXELS = "pexels"
    PIXABAY = "pixabay"
    LOCAL_SDXL = "local_sdxl"
    FAL_AI = "fal_ai"

@dataclass
class Visual:
    url: str
    source: VisualSource
    prompt: str
    cache_key: str
    generation_time_s: float = 0

class VisualAcquisitionManager:
    def __init__(self, pexels_key: str, pixabay_key: str, fal_key: str, cache_dir: str):
        self.pexels_key = pexels_key
        self.pixabay_key = pixabay_key
        self.fal_key = fal_key
        self.cache_dir = cache_dir  # SQLite cache: query_hash → result
        self.local_gen_semaphore = asyncio.Semaphore(1)  # Only 1 local gen at a time

    async def acquire(self, prompt: str, beat_id: str) -> Visual:
        """
        Acquire visual for given prompt.
        1. Check cache (24h TTL)
        2. Try Pexels
        3. Try Pixabay
        4. Try local SDXL (with timeout)
        5. Fall back to fal.ai
        """
        cache_key = f"{beat_id}_{hash(prompt)}"
        
        # Check cache
        cached = self._check_cache(cache_key)
        if cached:
            return Visual(cached["url"], cached["source"], prompt, cache_key)
        
        # Tier 1: Stock APIs (parallel)
        stock_tasks = [
            self._search_pexels(prompt),
            self._search_pixabay(prompt)
        ]
        stock_results = await asyncio.gather(*stock_tasks, return_exceptions=True)
        
        for result in stock_results:
            if isinstance(result, Visual) and result.url:
                self._cache_result(cache_key, result)
                return result
        
        # Tier 2: Local SDXL (with timeout + memory check)
        try:
            async with self.local_gen_semaphore:
                result = await asyncio.wait_for(
                    self._generate_local_sdxl(prompt),
                    timeout=45.0  # 45s timeout
                )
                if result:
                    self._cache_result(cache_key, result)
                    return result
        except asyncio.TimeoutError:
            print(f"Local generation timeout for: {prompt}")
        except Exception as e:
            print(f"Local generation error: {e}")
        
        # Tier 3: Cloud fallback (fal.ai)
        try:
            result = await self._generate_via_fal(prompt)
            self._cache_result(cache_key, result)
            return result
        except Exception as e:
            print(f"fal.ai generation failed: {e}")
            raise Exception(f"All visual acquisition tiers exhausted for: {prompt}")

    async def _search_pexels(self, query: str) -> Optional[Visual]:
        # Normalized query from shot beat
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": self.pexels_key}
            params = {"query": query, "per_page": 1}
            try:
                async with session.get("https://api.pexels.com/v1/search", 
                                      headers=headers, params=params, timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data["photos"]:
                            photo = data["photos"][0]
                            # Log remaining quota
                            remaining = r.headers.get("X-Ratelimit-Remaining")
                            print(f"Pexels remaining: {remaining}")
                            return Visual(
                                photo["src"]["medium"], 
                                VisualSource.PEXELS,
                                query, 
                                f"pexels_{photo['id']}"
                            )
            except asyncio.TimeoutError:
                pass
        return None

    async def _search_pixabay(self, query: str) -> Optional[Visual]:
        async with aiohttp.ClientSession() as session:
            params = {"key": self.pixabay_key, "q": query, "per_page": 1}
            try:
                async with session.get("https://pixabay.com/api/", 
                                      params=params, timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data["hits"]:
                            hit = data["hits"][0]
                            return Visual(
                                hit["largeImageURL"],
                                VisualSource.PIXABAY,
                                query,
                                f"pixabay_{hit['id']}"
                            )
            except asyncio.TimeoutError:
                pass
        return None

    async def _generate_local_sdxl(self, prompt: str) -> Optional[Visual]:
        """Local generation via diffusers + MPS"""
        try:
            # For simplicity, assume ComfyUI server at localhost:8188
            async with aiohttp.ClientSession() as session:
                workflow = self._build_sdxl_workflow(prompt)
                async with session.post("http://localhost:8188/prompt", json=workflow) as r:
                    if r.status == 200:
                        result = await r.json()
                        # Assume ComfyUI returns { "prompt_id": "...", "outputs": {...} }
                        # Poll for output or use WebSocket in production
                        return Visual(
                            f"file:///output/gen_{result['prompt_id']}.png",
                            VisualSource.LOCAL_SDXL,
                            prompt,
                            f"local_{result['prompt_id']}",
                            generation_time_s=25  # Average
                        )
        except Exception:
            pass
        return None

    async def _generate_via_fal(self, prompt: str) -> Visual:
        """fal.ai fallback (cost: $0.025/img Flux Pro)"""
        result = await fal_client.run_async(
            "fal-ai/flux-pro",
            arguments={
                "prompt": prompt,
                "image_size": {"width": 1024, "height": 1024},
                "num_images": 1,
                "seed": int(time.time())  # Vary results
            }
        )
        return Visual(
            result["images"][0]["url"],
            VisualSource.FAL_AI,
            prompt,
            f"fal_{int(time.time())}",
            generation_time_s=15
        )

    def _build_sdxl_workflow(self, prompt: str) -> dict:
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 0]}},
            "4": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal", "positive": ["3", 0], "negative": ["3", 1], "latent_image": ["5", 0]}},
            "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["6", 0], "vae": ["1", 2]}},
            "6": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "gen"}}
        }

    def _check_cache(self, cache_key: str) -> Optional[dict]:
        # SQLite query with TTL check (24h)
        pass

    def _cache_result(self, cache_key: str, visual: Visual):
        # SQLite insert with timestamp
        pass
```

---

## 5. Rate Limiting & Caching Strategy

### 5.1 Implementation (requests-cache + requests-ratelimiter)

```python
# visual_cache.py
import requests
from requests_cache import CachedSession
from requests_ratelimiter import LimiterSession
from datetime import timedelta

# Pexels: 200 req/hr = 3.33 req/sec
pexels_session = CachedSession(
    backend='sqlite',
    expire_after=timedelta(hours=24),  # Cache 24h per Pexels guidance
    pool_connections=5
)
pexels_session.headers.update({"Authorization": PEXELS_KEY})

# Apply rate limiter: 3 req/sec (conservative, allows bursts)
pexels_limiter = LimiterSession(
    per_second=3,
    per_minute=180,  # 200/hr ≈ 3.3/min
    session=pexels_session
)

# Pixabay: 100 req/60s = 1.67 req/sec, MUST cache 24h
pixabay_session = CachedSession(
    backend='sqlite',
    expire_after=timedelta(hours=24),  # MANDATORY per API docs
    pool_connections=5
)

pixabay_limiter = LimiterSession(
    per_second=1.5,  # Conservative for 100 req/60s
    session=pixabay_session
)

# Usage:
response = pexels_limiter.get("https://api.pexels.com/v1/search", 
                              params={"query": "shipwreck"})
# If cache hit: no rate limit cost (no API call)
# If cache miss: respects 3 req/sec limit, caches for 24h
```

### 5.2 Cache Expiry Monitoring

```python
# cache_monitor.py
import sqlite3
from datetime import datetime, timedelta

def check_cache_health(cache_db_path: str):
    conn = sqlite3.connect(cache_db_path)
    cursor = conn.cursor()
    
    # Query old cache entries (>24h)
    stale_cutoff = datetime.now() - timedelta(hours=24)
    cursor.execute("""
        SELECT COUNT(*) FROM cache 
        WHERE timestamp < ?
    """, (stale_cutoff.isoformat(),))
    
    stale_count = cursor.fetchone()[0]
    print(f"Stale entries (>24h): {stale_count}")
    
    # Cleanup
    cursor.execute("DELETE FROM cache WHERE timestamp < ?", (stale_cutoff.isoformat(),))
    conn.commit()
    conn.close()
```

---

## 6. Compliance & Licensing

### 6.1 License Summary

| Source | License | Attribution | YouTube OK? |
|--------|---------|-------------|-----------|
| **Pexels** | CC0 | Optional (appreciated) | ✅ Yes, no claim risk |
| **Pixabay** | Pixabay License (CC0-like) | Not required | ✅ Yes, explicitly safe |
| **Local SDXL-gen** | Model (Stability AI) | Model: CC (cite Stability), output: yours | ⚠️ Must tag as "AI-generated" |
| **fal.ai-gen** | Same as model | Must tag as "AI-generated" | ⚠️ Tag required |

### 6.2 Implementation (Tagging AI Images)

```python
# compliance_tagger.py
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def tag_ai_generated_image(image_path: str, output_path: str):
    """Add watermark/label for AI-generated images per compliance rules."""
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    # Small text in corner (bottom-right)
    text = "AI-Generated"
    font_size = int(img.height * 0.03)
    # Use system font (fallback)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    # Draw semi-transparent background
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.rectangle(bbox, fill=(0, 0, 0, 200))  # Black with alpha
    
    # Draw text (white)
    draw.text((img.width - bbox[2], img.height - bbox[3]), text, 
              font=font, fill=(255, 255, 255, 255))
    
    img.save(output_path, quality=95)
    print(f"Tagged AI image: {output_path}")
```

---

## 7. Gotchas & Troubleshooting

### Rate Limit Gotchas

| Gotcha | Symptom | Fix |
|--------|---------|-----|
| **Hitting Pexels 200 req/hr** | 429 Too Many Requests + X-Ratelimit-Reset | Batch searches (e.g., 1× per hour). Use cache. Request higher limits. |
| **Pixabay 24h cache requirement** | Legal risk if violated | Use requests-cache with `expire_after=timedelta(hours=24)`. Never bypass. |
| **Cache TTL too short** | Redundant API calls, quota wasted | Set to 24h minimum. Monitor stale entries weekly. |
| **API key in logs** | Security exposure | Use env vars. Never log `Authorization` header. |

### Generation Gotchas

| Gotcha | Symptom | Fix |
|--------|---------|-----|
| **Local SDXL model not downloaded** | First run hangs, 5-10 min delay | Pre-download on setup. Parallelize with other tasks. |
| **Memory OOM on M1 16GB** | Process killed, no error msg | Monitor RAM via Activity Monitor. Reduce batch size. Use smaller model (SD 1.5 instead of SDXL). |
| **ComfyUI WebSocket connection lost** | Hang indefinitely, no response | Add timeout (15s) on WebSocket wait. Reconnect logic. |
| **MPS device unavailable** | `RuntimeError: mps device not available` | Upgrade PyTorch: `pip install --upgrade torch`. Use CPU fallback (slow). |
| **Prompt too long (>100 tokens)** | Quality degrades, slower | Truncate shot prompt to <50 tokens. Use keywords instead of sentences. |
| **fal.ai rate limit (burst spike)** | 429 Limit Exceeded | Cap concurrent fal.ai requests to 2-3. Use exponential backoff (retry with 2s, 4s, 8s). |

### Timing Gotchas

| Source | Median Time | P95 Time | Budget for 3 vids/wk |
|--------|------------|----------|----------------------|
| Pexels API call | 0.5s | 2s | <5s total (cached) |
| Pixabay API call | 0.3s | 1.5s | <5s total (cached) |
| Local SDXL (M1 16GB) | 40s | 60s | 120s (3 imgs × 40s) |
| Local SDXL (M2 32GB) | 15s | 25s | 45s (3 imgs × 15s) |
| fal.ai Flux | 12s | 20s | 36s (3 imgs × 12s) |
| **Total (all tiers)** | ~60s (cached) or ~120s (gen) | | < 5 min/video feasible |

---

## 8. Recommendation Ranking

### Option A: **Stock-First + Local Fallback (RECOMMENDED)**
- **Stack**: Pexels + Pixabay (with 24h cache) → MLX-SDXL (ComfyUI) → fal.ai
- **Cost**: Free (unless 3+ vids exceed Pexels quota, then $0-5/mo on fal.ai)
- **Setup**: 2-3 hours (download models, test cache)
- **Maintenance**: 30 min/week (monitor quotas, cache cleanup)
- **Pros**: Minimal cost, reliable (stock quality), locally owned generation, compliance-clear
- **Cons**: Requires M1/M2/M3 16GB+ RAM, local setup complexity

**When to use**: Baseline strategy. Fits YAGNI (avoid unnecessary cloud spend).

### Option B: **Cloud-Centric (High Cost)**
- **Stack**: Pexels → fal.ai immediately (no local)
- **Cost**: $50-100/mo (at 30-50 images/mo from fal.ai)
- **Setup**: 30 min
- **Pros**: Simplest, no local setup, always fast
- **Cons**: High cost, vendor lock-in, less compliance control

**When to use**: When local SDXL fails repeatedly or user has budget priority.

### Option C: **Hybrid (Recommended Production)**
- **Stack**: Pexels (primary) → Pixabay (fallback) → MLX-SDXL (off-peak, <30s) → fal.ai (on-demand, pay/use)
- **Cost**: Free + $5-15/mo (occasional fal.ai)
- **Setup**: 3-4 hours
- **Maintenance**: 1 hour/week

**When to use**: Best balance for 3 videos/week with M2/M3 Mac.

---

## 9. Implementation Roadmap

### Phase 1: Stock API Integration (Week 1)
- [ ] Register Pexels + Pixabay keys
- [ ] Implement `requests-cache` + `requests-ratelimiter` wrapper
- [ ] Write shot-list keyword normalizer (LLM-based)
- [ ] Test Pexels/Pixabay search on sample beats

### Phase 2: Local SDXL Setup (Week 2)
- [ ] Install MLX framework (or diffusers + MPS)
- [ ] Download SDXL-base model (~6.5GB)
- [ ] Spin up ComfyUI server locally (optional, for node-based workflow)
- [ ] Test generation: simple prompt → measure time on target Mac

### Phase 3: Resilient Acquisition Layer (Week 3)
- [ ] Implement `VisualAcquisitionManager` (3-tier fallback)
- [ ] Add timeout/error handling (45s local, 5s API)
- [ ] Test failover: stock → local → fal.ai
- [ ] Log metrics (source, time, cost)

### Phase 4: Compliance & Tagging (Week 4)
- [ ] Add AI-generation watermark/tag
- [ ] Verify license attribution in output
- [ ] Test YouTube upload with compliance labels
- [ ] Document for review gate

---

## 10. Unresolved Questions

1. **Will user have M1/M2/M3 Mac with 16GB+ RAM?** (Affects local SDXL feasibility)
2. **Budget cap on cloud generation (fal.ai)?** (If $0, skip fal.ai; if $100+/mo, can use fal.ai primary)
3. **Shot-list generation**: Will LLM produce shot beats automatically, or require manual input?
4. **Pixabay permanence**: Will we maintain a local archive of downloaded images, or always fetch?
5. **Diffusers vs MLX**: Should we prototype both on target Mac and benchmark, or commit to MLX immediately?

---

## Sources & References

- [Pexels API Documentation](https://www.pexels.com/api/documentation/)
- [How to avoid rate limits - Pexels](https://help.pexels.com/hc/en-us/articles/900006470063-What-steps-can-I-take-to-avoid-hitting-the-rate-limit)
- [Pixabay API Docs](https://pixabay.com/api/docs/)
- [MLX Framework (Apple)](https://github.com/ml-explore/mlx)
- [Stable Diffusion with Core ML on Apple Silicon](https://machinelearning.apple.com/research/stable-diffusion-coreml-apple-silicon)
- [How to use Stable Diffusion in Apple Silicon - Hugging Face](https://huggingface.co/docs/diffusers/v0.6.0/en/optimization/mps)
- [ComfyUI GitHub](https://github.com/comfy-org/comfyui)
- [ComfyUI API Guide (Medium)](https://medium.com/@next.trail.tech/how-to-use-comfyui-api-with-python-a-complete-guide-f786da157d37)
- [fal.ai vs Replicate Pricing 2026](https://modelslab.com/blog/api/stable-diffusion-api-vs-replicate-vs-fal-ai-2026)
- [AI API Timeout & Fallback Strategies](https://evolink.ai/blog/ai-api-timeout-retry-fallback)
- [Python Rate Limiting - requests-ratelimiter](https://github.com/JWCook/requests-ratelimiter)
- [ComfyUI on Apple Silicon 2025 (Medium)](https://medium.com/@tchpnk/comfyui-on-apple-silicon-from-scratch-2025-9facb41c842f)

---

**Report Date**: 2026-07-08  
**Research Duration**: 2 hours  
**Researcher**: Technical Analyst  
**Status**: COMPLETE
