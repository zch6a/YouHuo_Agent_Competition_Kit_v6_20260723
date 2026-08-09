/**
 * 对话消息的 LazyForEach 数据源。
 *
 * 原来的实现用 `ForEach` 直接铺整个数组。对话是只增不减的：聊够十分钟就有上百条
 * 消息，而 ForEach 每次状态变化都会把它们全部重建一遍——在这个受众实际持有的
 * 入门级设备上，这就是打完一句字、气泡半秒后才出现的那半秒。LazyForEach 只渲染
 * 可视区域附近的项。
 */

export interface MessageItem {
  /** 稳定且唯一。LazyForEach 靠它决定复用哪个节点，用 index 当 key 会在插入时错位。 */
  id: string;
  role: string;
  text: string;
}

/**
 * 这个基类存在的唯一原因，是 `DataChangeListener` 在当前 SDK 上同时要求新旧两套
 * 方法名（`onDataAdd` 和已废弃的 `onDataAdded`……）。少写一个就是编译错误，而错误
 * 信息只会说"未实现接口"，不会说少了哪一个。集中在这里实现一次。
 */
abstract class BasicDataSource<T> implements IDataSource {
  private listeners: DataChangeListener[] = [];

  abstract totalCount(): number;

  abstract getData(index: number): T;

  registerDataChangeListener(listener: DataChangeListener): void {
    if (this.listeners.indexOf(listener) < 0) {
      this.listeners.push(listener);
    }
  }

  unregisterDataChangeListener(listener: DataChangeListener): void {
    const pos = this.listeners.indexOf(listener);
    if (pos >= 0) {
      this.listeners.splice(pos, 1);
    }
  }

  protected notifyDataReload(): void {
    this.listeners.forEach((listener: DataChangeListener) => {
      listener.onDataReloaded();
    });
  }

  protected notifyDataAdd(index: number): void {
    this.listeners.forEach((listener: DataChangeListener) => {
      listener.onDataAdd(index);
    });
  }

  protected notifyDataChange(index: number): void {
    this.listeners.forEach((listener: DataChangeListener) => {
      listener.onDataChange(index);
    });
  }

  protected notifyDataDelete(index: number): void {
    this.listeners.forEach((listener: DataChangeListener) => {
      listener.onDataDelete(index);
    });
  }
}

export class MessageSource extends BasicDataSource<MessageItem> {
  private items: MessageItem[] = [];
  private seq: number = 0;

  totalCount(): number {
    return this.items.length;
  }

  getData(index: number): MessageItem {
    return this.items[index];
  }

  /** 返回新消息的下标，调用方用它把列表滚到底。 */
  append(role: string, text: string): number {
    this.seq++;
    this.items.push({ id: `m${this.seq}`, role, text });
    const index = this.items.length - 1;
    // 只通知"新增了第 index 条"，而不是整表重载：重载会让已经渲染好的气泡全部
    // 重建，滚动位置也会跳。
    this.notifyDataAdd(index);
    return index;
  }

  /**
   * 就地改写最后一条。用于把"正在听……"占位替换成真正的回复——新增再删除会让
   * 列表在半秒里跳两次。
   */
  replaceLast(text: string): void {
    if (this.items.length === 0) {
      return;
    }
    const index = this.items.length - 1;
    const current = this.items[index];
    this.items[index] = { id: current.id, role: current.role, text };
    this.notifyDataChange(index);
  }

  lastIndex(): number {
    return this.items.length - 1;
  }
}
