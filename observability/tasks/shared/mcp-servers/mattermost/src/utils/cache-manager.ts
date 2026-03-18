/**
 * キャッシュアイテムの内部構造
 */
interface CacheItem<T = any> {
  value: T;
  expiry: number | null;
}

/**
 * シンプルなインメモリキャッシュマネージャー
 */
class CacheManager {
  private cache: Map<string, CacheItem> = new Map<string, CacheItem>();

  /**
   * キャッシュに値を保存
   * @param key - キー
   * @param value - 値
   * @param ttlSeconds - 有効時間（秒）
   */
  set(key: string, value: any, ttlSeconds: number): void {
    const item: CacheItem = {
      value: value, // eslint-disable-line @typescript-eslint/no-unsafe-assignment
      expiry: ttlSeconds > 0 ? Date.now() + ttlSeconds * 1000 : null,
    };
    this.cache.set(key, item);
  }

  /**
   * キャッシュから値を取得
   * @param key - キー
   * @returns 値。存在しないか期限切れの場合はnull
   */
  get(key: string): any {
    const item = this.cache.get(key);
    if (!item) return null;

    // 期限チェック
    if (item.expiry && Date.now() > item.expiry) {
      this.cache.delete(key);
      return null;
    }

    return item.value;
  }

  /**
   * キーが存在し、期限切れでないかチェック
   * @param key - キー
   * @returns 存在するかどうか
   */
  has(key: string): boolean {
    return this.get(key) !== null;
  }

  /**
   * 特定のキーを削除
   * @param key - キー
   * @returns 削除できたかどうか
   */
  delete(key: string): boolean {
    return this.cache.delete(key);
  }

  /**
   * 全てのキャッシュをクリア
   */
  clear(): void {
    this.cache.clear();
  }

  /**
   * 期限切れのキャッシュを削除
   * @returns 削除されたキーの数
   */
  cleanup(): number {
    const now = Date.now();
    let deleted = 0;

    for (const [key, item] of this.cache) {
      if (item.expiry && now > item.expiry) {
        this.cache.delete(key);
        deleted++;
      }
    }

    return deleted;
  }
}

// シングルトンインスタンス
const cacheManager = new CacheManager();

export default cacheManager;
