import random

from card_guess.cards import load_game_cards, render_description
from card_guess.puzzle import (
    build_puzzle,
    find_opening_reveal_positions,
    format_rarity,
)
from card_guess.game import GameState

def show_puzzle(puzzle):
    print()
    print("=== 本轮题目 ===")
    print(f"牌名：{puzzle['masked_name']}")
    print(f"来源：{puzzle['pool']}")
    print(f"类型：{puzzle['type']}")
    print(f"费用：{puzzle['cost']}")

    if puzzle["star_cost"] is not None:
        print(f"辉星费用：{puzzle['star_cost']}")

    if puzzle.get("rarity") is not None:
        print(f"稀有度：{puzzle['rarity']}")

    print("描述：")
    print(puzzle["masked_description"])
    print()


def show_status(game):
    wrong_text = "暂无" if not game.wrong_guesses else "、".join(game.wrong_guesses)
    print(f"已猜错：{wrong_text}")
    print(f"累计猜测：{game.total_guess_count} 次")


def main():
    mode = input("选择模式（回车=混合，1=塔1卡池，2=塔2卡池）：").strip()

    if mode == "1":
        mode = "sts1"
    elif mode == "2":
        mode = "sts2"
    else:
        mode = "mixed"

    cards = load_game_cards(mode)
    card = random.choice(cards)

    game = GameState(card)

    game.revealed_positions.update(
        find_opening_reveal_positions(
            render_description(card)
        )
    )

    puzzle = build_puzzle(
        card,
        revealed_positions=game.revealed_positions,
        revealed_name_positions=game.revealed_name_positions,
        rarity_revealed=game.rarity_revealed,
    )

    # 这里才真正把谜面显示出来
    show_puzzle(puzzle)
    show_status(game)

    # 这里才真正开始不断猜
    while not game.ended:
        answer = input("请输入卡牌名或描述片段（输入 end 或 结束 结束本轮）：").strip()

        if answer.lower() == "结束" or answer.lower() == "end":
            real_answer = game.end()
            print(f"本轮结束，正确答案是：{real_answer}")
            break

        result = game.handle_input(answer)

        if result.status == "correct":
            print(f"猜对了！答案就是：{card['name']}")
            break

        if result.status == "revealed":
            if game.ended and result.reveal_target == "name":
                print(f"牌名已全部揭开，本轮结束，正确答案是：{card['name']}")
                break

            if result.reveal_target == "name":
                print(f"🎯 牌名命中！揭开 {result.revealed_count} 个新字符！")
            else:
                print(f"🎯 描述命中！揭开 {result.revealed_count} 个新字符！")

            puzzle = build_puzzle(
                card,
                revealed_positions=game.revealed_positions,
                revealed_name_positions=game.revealed_name_positions,
                rarity_revealed=game.rarity_revealed,
            )
            show_puzzle(puzzle)
            show_status(game)
            continue

        if result.status == "already_revealed":
            print("这部分已经揭开了，换个地方猜吧。")
            continue

        if result.status == "invalid":
            print("这个输入没有可猜的文字。")
            continue

        if result.status == "wrong":
            print(f"猜错了，当前错误次数：{game.wrong_count}")

            if result.hint_type == "rarity":
                print(f"提示：稀有度为 {format_rarity(card)}")
            elif result.hint_type == "description":
                print("提示：揭开了新的描述内容。")
            elif result.hint_type == "name":
                print("提示：揭开了一个牌名字符。")

            if game.ended:
                print(f"提示耗尽，本轮结束，正确答案是：{card['name']}")
                break

            puzzle = build_puzzle(
                card,
                revealed_positions=game.revealed_positions,
                revealed_name_positions=game.revealed_name_positions,
                rarity_revealed=game.rarity_revealed,
            )
            show_puzzle(puzzle)
            show_status(game)


if __name__ == "__main__":
    main()
