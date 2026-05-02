# Django 面试八股（速答版）

> 目标：用“先一句话结论 → 关键机制 → 代码/配置要点 → 常见追问”组织回答。

---

## 1) MTV（Model / Template / View）

### 一句话回答
Django 采用 **MTV**：`Model` 管数据与业务对象，`Template` 负责展示，`View` 负责请求处理与业务编排；本质上与 MVC 类似，只是命名不同。

### 你可以展开的 4 点
- **Model**：定义数据结构（字段、约束、关系）以及与数据库交互的 ORM 能力。
- **View**：接收 request，做鉴权/参数校验/调用 service/ORM，最后返回 response（HTML/JSON/重定向）。
- **Template**：把 view 传入的 context 渲染成 HTML；尽量避免复杂业务逻辑。
- **URLconf**：URL 路由把请求分发到 view（Django 的请求入口常被一起问）。

### 常见追问
- **MTV vs MVC 怎么对应？**
  - Django `View` ≈ MVC 的 Controller
  - Django `Template` ≈ MVC 的 View
  - Django `Model` ≈ MVC 的 Model
- **一次请求的生命周期？**（可简述）
  - WSGI/ASGI → URL 路由 → 中间件（进）→ View → Template/序列化 → 中间件（出）→ Response

---

## 2) ORM：QuerySet 惰性查询、`select_related` 连表

### 一句话回答
Django ORM 的 `QuerySet` 是**惰性执行**的：构造查询不会立刻打 DB，只有在“需要数据”的时刻才会执行；`select_related` 通过 SQL JOIN 预取外键/一对一关联，避免 N+1。

### QuerySet 什么时候会真的执行（触发查询）
常见触发点：
- 迭代：`for obj in qs:`
- 强制转换：`list(qs)`
- 取长度：`len(qs)`（会把结果拉回）
- 布尔判断：`if qs:`（会执行查询）
- 切片取值：`qs[0]`（可能触发 LIMIT 查询）
- 聚合/统计：`count() / exists() / aggregate()`（走 SQL）

### `select_related` vs `prefetch_related`
- `select_related`：适合 **ForeignKey / OneToOne**（单值关系），通过 JOIN 一次查齐。
- `prefetch_related`：适合 **ManyToMany / 反向 ForeignKey**（多值关系），通常是“主表查询 + 关联表二次查询”，在 Python 侧做合并。

### 典型面试例子（N+1）
- 场景：`Book` 有外键 `author`，列表页展示作者名。
- 不优化：循环里访问 `book.author.name` 会导致 N+1。
- 优化：

```python
books = Book.objects.select_related('author').all()
for b in books:
    print(b.author.name)  # 不再额外查 author
```

### 易错点（加分）
- `only()/defer()` 与 `select_related()` 混用时要注意字段延迟加载可能引发额外查询。
- `values()/values_list()` 返回的是字典/元组，不是 model 实例；`select_related` 对其意义有限。
- 调试 SQL：`str(qs.query)`、Django Debug Toolbar（开发环境）。

---

## 3) 迁移：`makemigrations` 生成、`migrate` 同步

### 一句话回答
迁移分两步：`makemigrations` 根据模型变化生成迁移文件（记录“如何变更”），`migrate` 把迁移应用到数据库（真正执行 DDL）。

### 关键点（面试常问）
- **迁移文件是什么**：它是可回放的 schema 变更脚本（Python 表达）。
- **依赖与顺序**：Django 会根据 migration 依赖图决定执行顺序。
- **多人协作冲突**：不同分支可能产生迁移冲突，需要 `makemigrations --merge` 或手工调整依赖。

### 常见命令（知道即可）
- 查看计划：`python manage.py showmigrations`、`python manage.py migrate --plan`
- 迁移到某个版本：`python manage.py migrate app 0002`
- 假迁移：`python manage.py migrate --fake`（DB 已改但迁移记录没跟上时使用，谨慎）

### 追问：迁移为什么安全/不安全？
- 生产要注意：大表加列/建索引/改类型可能锁表；常用策略是分步骤迁移、在线 DDL、灰度。

---

## 4) CBV（类视图） vs FBV（函数视图）

### 一句话回答
FBV 简单直观，适合轻量逻辑；CBV 更利于复用与扩展（继承、Mixin、通用视图），在复杂业务和标准 CRUD 场景更常用。

### 对比要点
- **可复用性**：CBV 可通过 Mixin/继承复用逻辑；FBV 通常靠装饰器/手工抽函数。
- **可读性**：FBV 一眼看到流程；CBV 需要理解 dispatch、HTTP method 映射与 MRO。
- **扩展性**：CBV 更容易做统一鉴权、分页、序列化等“横切能力”。

### CBV 的关键机制（常被追问）
- 入口是 `dispatch`：根据请求方法分发到 `get/post/put/delete`。

```python
from django.views import View
from django.http import JsonResponse

class PingView(View):
    def get(self, request):
        return JsonResponse({'ok': True})
```

### 加分点：Django REST framework（如果你简历提到）
- DRF 的 `APIView/ViewSet` 是 CBV 思想的进一步封装：认证、权限、节流、序列化、分页都可插拔。

---

## 5) 中间件：全局拦截、CSRF 防跨站

### 中间件（Middleware）

#### 一句话回答
中间件是 Django 请求/响应链路上的“洋葱模型”拦截器：请求进来会依次经过中间件，响应返回会反向经过中间件；适合做鉴权、日志、限流、异常处理等。

#### 核心点
- 顺序由 `MIDDLEWARE` 配置决定。
- 同一中间件既能处理 request，也能处理 response；异常也可在中间件层统一兜底。

#### 常见追问
- **为什么有的中间件必须放前面/后面？**
  - 因为依赖其他中间件设置的属性（例如认证信息、Session）。

---

### CSRF（跨站请求伪造）

#### 一句话回答
CSRF 的本质是：攻击者诱导已登录用户在“带着 Cookie”情况下对站点发起非预期请求。Django 通过 **CSRF Token** 校验（配合同源/Referer 检查、Cookie 策略）来阻止这类请求。

#### Django 里怎么做（答法要点）
- 对有副作用的请求（POST/PUT/PATCH/DELETE）要求携带 CSRF token。
- 模板表单：`{% csrf_token %}` 自动插入隐藏字段。
- AJAX：把 token 放在请求头（常见是 `X-CSRFToken`）。
- 极少数接口（如第三方回调）可以 `@csrf_exempt`，但要用签名/白名单等替代防护。

#### 追问：CSRF 与 XSS 的区别
- **XSS**：把恶意脚本注入到页面里执行，重点是“脚本执行”。
- **CSRF**：利用浏览器自动带 Cookie 的特性伪造请求，重点是“伪造请求”。
- 关系：XSS 可能窃取 CSRF token，从而绕过 CSRF 防护，所以两者都要做。

---

## 面试快速结尾句（可选）
如果面试官继续深挖，可以用：
- “我一般先用 Debug Toolbar 看 SQL 次数，再用 `select_related/prefetch_related` 消除 N+1。”
- “迁移到生产我会关注锁表风险，优先拆分迁移并在低峰执行。”
- “CBV 我会用 mixin 把鉴权/分页/序列化抽出来，保证视图层薄。”
