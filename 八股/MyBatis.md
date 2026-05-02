# MyBatis 面试八股（速答版）

> 结构：一句话结论 → 关键机制 → 常见追问 → 易错点/实战建议 → 示例代码。

---

## 1) `#{}` vs `${}`：预编译防注入 vs 字符串拼接

### 一句话回答
- `#{}` 是 **参数占位符**，会走 JDBC `PreparedStatement` 预编译绑定参数，能有效防 SQL 注入。
- `${}` 是 **字符串拼接**，把值原样拼到 SQL 里，易产生 SQL 注入风险，通常只用于“列名/表名/排序字段”等无法参数化的位置，并且必须做白名单校验。

### 典型示例
```xml
<select id="getById" resultType="User">
  select * from user where id = #{id}
</select>

<select id="listOrderBy" resultType="User">
  select * from user order by ${orderBy}
</select>
```

### 面试加分点：什么时候不得不用 `${}`？
- 动态表名、动态列名、`order by` 字段。
- **正确答法**：`${}` 只能用于“结构性片段”，并且要做 **枚举/白名单**，绝不接受用户原始输入。

---

## 2) 一级缓存：SqlSession 会话级，默认开启

### 一句话回答
MyBatis **一级缓存**是 `SqlSession` 级别的本地缓存，默认开启；同一个 `SqlSession` 内相同 statement + 参数的查询会命中缓存，减少重复 SQL。

### 什么时候会失效/清空（常问）
- 执行 `insert/update/delete` 后（默认会清空以保证一致性）
- 手动 `sqlSession.clearCache()`
- `sqlSession.commit()` / `rollback()`（一般会清空）
- 不同 `SqlSession` 之间不共享

### 常见追问
- **为什么我同样查询没有命中？**
  - 可能不是同一个 `SqlSession`（Spring 下通常一个事务对应一个 SqlSession）
  - 查询条件/分页参数不同
  - 中间有更新操作触发清空

---

## 3) 二级缓存：Mapper 级，需手动开启

### 一句话回答
MyBatis **二级缓存**是 `Mapper`（namespace）级别、跨 `SqlSession` 共享的缓存，需要显式开启（全局 + mapper 级），并且对象需要可序列化；其一致性要靠失效策略控制。

### 开启方式（常见配置）
- 全局：`cacheEnabled=true`
- mapper.xml：添加 `<cache/>` 或自定义缓存实现

```xml
<mapper namespace="com.example.UserMapper">
  <cache/>
</mapper>
```

### 易错点（面试很爱问）
- 二级缓存的写入通常发生在 `SqlSession` 提交/关闭时，没提交可能看不到缓存效果。
- 任意更新会按 namespace 维度清空（默认策略），可能导致命中率不如预期。
- 分布式场景二级缓存不适合直接当全局缓存（多节点一致性复杂），更常用 Redis。

---

## 4) 核心：接口 + XML（或注解），SQL 映射而非全自动 ORM

### 一句话回答
MyBatis 本质是 **SQL 映射框架**：开发者掌控 SQL（XML/注解），框架负责把“参数 → SQL → ResultSet → Java 对象”做映射；比起全自动 ORM，更可控、更适合复杂查询与性能调优。

### 关键组件（能说出来就加分）
- `MapperProxy`：把接口方法调用代理成执行 mappedStatement
- `Executor`：执行器（Simple/Reuse/Batch）
- `StatementHandler/ParameterHandler/ResultSetHandler`：执行与参数/结果处理

---

## 5) 延迟加载：按需查询，提升性能（但要防 N+1）

### 一句话回答
延迟加载（lazy loading）让关联对象在“真正访问时”才触发查询，减少不必要的 join/查询；但如果访问列表中每个对象的关联字段，可能产生 **N+1** 问题。

### 常见配置点（概念性即可）
- `lazyLoadingEnabled=true`
- `aggressiveLazyLoading=false`（避免一访问一个属性就把所有懒加载都加载了，具体行为取决于版本配置）

### 高频追问
- **如何避免 N+1？**
  - 该 join 的 join（一次查齐）
  - 或改成批量查询（一次查所有关联，再组装）
  - 或在 service 层控制访问模式，避免循环触发懒加载

---

## 6) 常考补充（建议掌握的“救命题”）

### 6.1 动态 SQL（MyBatis 核心竞争力）
- 常用标签：`<if>`、`<where>`、`<set>`、`<choose>`、`<foreach>`

```xml
<select id="list" resultType="User">
  select * from user
  <where>
    <if test="name != null and name != ''"> and name = #{name} </if>
    <if test="status != null"> and status = #{status} </if>
  </where>
</select>
```

### 6.2 `resultType` vs `resultMap`
- `resultType`：字段名与属性名能自动映射时够用。
- `resultMap`：字段别名、嵌套映射、复杂对象、关联关系时更稳。

### 6.3 分页
- 物理分页：SQL `limit offset, size`（深分页会慢）。
- 常用：分页插件（拦截器改写 SQL）或游标分页（基于 id）。

### 6.4 插件（Interceptor）机制
- MyBatis 插件基于责任链，常用于：分页、审计、SQL 打印、数据权限。
- 面试答法：插件通过拦截 `Executor/StatementHandler/ParameterHandler/ResultSetHandler` 的方法并动态代理增强。

### 6.5 批处理与 Executor
- `ExecutorType.BATCH` 可以批量发送，减少网络往返；但要注意事务边界、内存占用与失败回滚。

### 6.6 Spring 事务下的 SqlSession
- Spring 集成后通常使用 `SqlSessionTemplate`，在事务内复用同一个 `SqlSession`，从而一级缓存更容易生效。

---

## 7) 面试快速结尾句（可选）
- “我一般默认用 `#{}`，`${}` 只用于 order by/表名这类结构性片段并做白名单。”
- “缓存我会优先说清一级缓存是 SqlSession 级别；二级缓存 namespace 级别但分布式一致性复杂，生产常用 Redis 做集中式缓存。”
- “延迟加载能省查询，但要警惕 N+1，列表场景通常用 join 或批量加载。”
