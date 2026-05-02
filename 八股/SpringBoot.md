# Spring Boot 面试八股（速答版）

> 结构：一句话结论 → 核心机制 → 启动流程 → 配置与环境 → Bean 与作用域 → 常考补充 → 常见坑。

---

## 1) 核心：自动配置 / 起步依赖 / 嵌入式容器

### 一句话回答
Spring Boot 的核心价值是“约定优于配置”：通过 **Starter 起步依赖**统一依赖版本与常用组件组合，通过 **自动配置**按 classpath 与配置项自动装配 Bean，并用 **嵌入式容器**（Tomcat/Jetty/Undertow）实现开箱即用的可运行应用。

---

## 2) `@SpringBootApplication`：3 注解合体

### 一句话回答
`@SpringBootApplication` 等价于：
- `@SpringBootConfiguration`（本质是 `@Configuration`）
- `@EnableAutoConfiguration`（开启自动配置）
- `@ComponentScan`（默认从当前包向下扫描组件）

### 高频追问
- **为什么启动类要放在根包？**
  - 因为 `@ComponentScan` 默认扫描启动类所在包及其子包；放错位置会导致 Bean 扫描不到。

---

## 3) 自动配置：`@EnableAutoConfiguration` 怎么“加载配置”？

### 一句话回答
自动配置的本质是：Spring Boot 在启动时从约定的位置加载一批“自动配置类”，并通过大量 **条件注解（Conditional）** 判断当前环境是否满足，满足才注册相关 Bean。

### 面试能说到这几层就很稳
- 自动配置类来源：Starter 里声明的自动配置（不同 Boot 版本机制有所不同，但核心思想一致：框架会在启动阶段收集并导入这些配置类）。
- 生效条件：
  - `@ConditionalOnClass`：类路径存在某类
  - `@ConditionalOnMissingBean`：容器中不存在某 Bean 时才创建默认 Bean
  - `@ConditionalOnProperty`：配置项开关
  - `@ConditionalOnWebApplication`：是否 Web 环境

### 伪代码（帮助你口述）
```text
启动时：
1) 收集所有 AutoConfiguration 类
2) 按条件注解过滤
3) import 到容器，注册 BeanDefinition
4) 用户自定义 Bean 可通过 @ConditionalOnMissingBean 覆盖默认实现
```

---

## 4) 生命周期：启动 → 加载上下文 → 初始化 Bean → 运行

### 一句话回答
Spring Boot 启动大致是：创建并准备 `ApplicationContext` → 读取配置与自动配置 → 扫描/注册 BeanDefinition → 实例化单例 Bean → 完成容器刷新 → 启动 Web 容器（若是 Web 应用）→ 进入运行态。

### 常见追问（会说就加分）
- **Bean 初始化顺序你能介入吗？**
  - `BeanFactoryPostProcessor`（改 BeanDefinition）
  - `BeanPostProcessor`（改 Bean 实例）
  - `InitializingBean` / `@PostConstruct`（初始化回调）
  - `ApplicationRunner/CommandLineRunner`（应用启动后执行）

---

## 5) 配置：application.yml/properties，多环境切换

### 一句话回答
Spring Boot 通过“配置属性绑定（Configuration Properties）+ Profile 多环境”实现不同环境的差异化配置；常见是 `application.yml` 配合 `application-dev.yml` / `application-prod.yml`。

### Profile 怎么切换（口述即可）
- 配置：`spring.profiles.active=dev`
- 启动参数：`--spring.profiles.active=prod`
- 环境变量：`SPRING_PROFILES_ACTIVE=prod`

### 加分点：类型安全配置绑定
- 用 `@ConfigurationProperties(prefix="...")` 把配置映射到对象，避免散落的 `@Value`。

```java
@ConfigurationProperties(prefix = "app")
public class AppProperties {
    private String name;
    // getter/setter
}
```

---

## 6) Bean 作用域：单例 / 原型 / 请求 / 会话

### 一句话回答
- `singleton`：容器内单例（默认）
- `prototype`：每次获取创建一个新实例（容器不管理其完整生命周期销毁）
- `request`：一次 HTTP 请求一个实例（Web 环境）
- `session`：一次会话一个实例（Web 环境）

### 高频追问：单例里注入原型会怎样？
- 直接注入会在单例创建时把原型实例确定下来，后续不会每次都是新的。
- 常用解决：`ObjectProvider`/`Provider`、方法注入（`@Lookup`）、工厂模式。

---

## 7) 常考补充（建议你项目里能兜住）

### 7.1 Starter 起步依赖是什么？
- Starter 本质是“依赖聚合 + 自动配置”：
  - `spring-boot-starter-web` 拉来 Spring MVC、Jackson、验证、嵌入式容器等依赖。

### 7.2 外部化配置优先级（常问但不需要死背）
- 口述要点即可：命令行参数/环境变量通常优先于配置文件；配置文件里 profile 专属配置覆盖默认。

### 7.3 Actuator（运维必问）
- 健康检查、指标、信息端点：`/actuator/health`、`/actuator/metrics`。
- 生产要注意：端点暴露范围、鉴权、敏感信息脱敏。

### 7.4 自动配置“如何自定义覆盖”？
- 通过自己定义同类型 Bean（常见与 `@ConditionalOnMissingBean` 配合）。
- 通过配置项开关（`@ConditionalOnProperty`）。

### 7.5 嵌入式容器与部署形态
- `jar` 直接运行（嵌入式容器）
- `war` 部署到外部容器（较少见）

---

## 8) 常见坑（面试很爱追）

- **自动配置没生效**：缺依赖/类不在 classpath；条件注解未满足；Bean 被你自己覆盖。
- **配置不生效**：profile 没激活；配置文件放错位置；属性名写错。
- **组件扫描不到**：启动类包路径不对，或你自定义了 `@ComponentScan` 限制范围。
- **循环依赖**：设计问题，尽量拆分职责；必要时用延迟注入（但不推荐靠它治本）。

---

## 面试快速结尾句（可选）
- “我理解 Spring Boot 的核心就是 Starter + 自动配置 + 外部化配置，启动阶段通过条件注解选择性装配 Bean；排查自动配置我会看条件不满足、依赖是否在 classpath、以及是否被自定义 Bean 覆盖。”
