# AOP（Spring）面试八股（速答版）

> 结构：一句话结论 → 核心概念 → 代理机制 → 通知类型 → 常见场景 → 高频坑与追问 → 示例代码。

---

## 1) AOP 是什么？

### 一句话回答
AOP（面向切面编程）把“日志、事务、权限、监控”等**横切关注点**从业务代码里抽离出来，通过在方法调用前后织入增强逻辑，实现“业务代码更干净、复用更强、改动面更小”。

### 常见追问
- **AOP 和 OOP 的关系？**
  - OOP 解决纵向（对象/继承）复用；AOP 解决横向（跨多个模块的通用能力）复用。

---

## 2) 核心概念：切面、切点、通知、连接点

### 一句话记忆版
- **切面（Aspect）**：横切逻辑的“集合”（类）
- **通知（Advice）**：具体“什么时候做什么”（方法）
- **切点（Pointcut）**：在哪些位置织入（表达式/规则）
- **连接点（Joinpoint）**：程序执行过程中可被织入的点（方法调用/异常抛出等；Spring 主要是方法级）

### 口述模板
“我会先定义切点匹配哪些方法，然后在切面里用不同通知类型（前置/环绕/异常等）把增强织入到这些连接点上。”

---

## 3) 代理：JDK（接口） vs CGLIB（子类）

### 一句话回答
Spring AOP 基于**代理**实现：
- 目标类有接口时默认用 **JDK 动态代理**（生成接口实现类）
- 没有接口或强制时用 **CGLIB**（生成子类字节码）

### 对比要点（面试常问）
- **JDK 动态代理**
  - 优点：不需要继承目标类；更贴合面向接口编程
  - 限制：必须有接口（代理的是接口方法）
- **CGLIB**
  - 优点：无接口也能代理
  - 限制：通过继承实现；`final` 类/`final` 方法无法被代理（无法覆写）；构造等细节也有限制

### 高频追问：怎么强制用 CGLIB？
- 常见做法（不同 Spring 版本略有差异）：配置 `proxyTargetClass=true`（例如 `@EnableAspectJAutoProxy(proxyTargetClass = true)` 或配置项）。

---

## 4) 通知类型：前置 / 后置 / 环绕 / 异常 / 最终

### 一句话回答
通知描述增强逻辑在目标方法生命周期的切入点：
- **前置（Before）**：方法执行前
- **后置（AfterReturning）**：方法正常返回后
- **环绕（Around）**：包住方法执行（最强，可控是否执行/执行多次/修改返回值）
- **异常（AfterThrowing）**：方法抛异常时
- **最终（After）**：类似 finally，无论成功/异常都会执行

### 面试加分点
- 你只要说清：**性能统计/链路追踪更适合 Around**（能拿到耗时、也能统一处理异常）。

---

## 5) 典型场景：日志、事务、权限、监控

### 一句话回答
- **日志**：记录入参/出参、traceId、错误堆栈
- **事务**：在方法边界开启/提交/回滚（`@Transactional`）
- **权限**：方法级鉴权（角色/资源）
- **监控**：耗时、QPS、异常率，打点到 Prometheus/日志

---

## 6) 高频坑与追问（最容易被问倒的部分）

### 6.1 “AOP 不生效”的经典原因：自调用（self-invocation）
- 场景：同一个类里 `methodA()` 调用 `this.methodB()`，即使 `methodB` 有事务/切面，也可能不走代理。
- 原因：调用发生在对象内部，没有经过 Spring 生成的代理对象。
- 常见解决：
  - 把 `methodB` 抽到另一个 Bean；
  - 或通过注入代理再调用（不推荐滥用）；
  - 或使用 AspectJ 编织（更强但复杂）。

### 6.2 private/final 方法能不能被 AOP 增强？
- Spring AOP 基于代理：通常只能拦截 **public/protected** 的可代理方法；
- CGLIB 无法覆写 `final`；private 方法也无法被子类覆写，因此通常无法增强。

### 6.3 事务与 AOP 的关系（非常高频）
- `@Transactional` 本质也是 AOP：在方法边界做开启/提交/回滚。
- 常见追问：
  - **只有运行时异常才回滚吗？** 默认回滚 `RuntimeException/Error`，可配置 `rollbackFor`。
  - **事务传播行为？** `REQUIRED/REQUIRES_NEW/NESTED` 等（建议至少会讲 REQUIRED vs REQUIRES_NEW）。

### 6.4 多个切面顺序如何控制？
- 常见：用 `@Order` 或实现 `Ordered` 控制执行顺序。

---

## 7) 最小示例：Spring AOP 记录方法耗时（Around）

```java
@Aspect
@Component
public class TimingAspect {

    @Pointcut("execution(* com.example.service..*(..))")
    public void serviceMethods() {}

    @Around("serviceMethods()")
    public Object timing(ProceedingJoinPoint pjp) throws Throwable {
        long start = System.currentTimeMillis();
        try {
            return pjp.proceed();
        } finally {
            long cost = System.currentTimeMillis() - start;
            String method = pjp.getSignature().toShortString();
            System.out.println(method + " cost=" + cost + "ms");
        }
    }
}
```

> 面试说明：这里用 `execution(...)` 作为切点表达式；生产会换成日志框架 + traceId，并避免打印敏感信息。

---

## 面试快速结尾句（可选）
- “AOP 我会用在横切逻辑，比如日志/监控/权限；事务也是 AOP 的一种。代理方式上，接口默认 JDK 代理，无接口用 CGLIB；排查不生效我会优先看自调用、方法修饰符、final/private、切点是否匹配。”
