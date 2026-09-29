from radar.enumerate import slugs_from_text


def test_slugs_from_text_extracts_unique_board_slugs_and_skips_vendor_hosts():
    text = "\n".join([
        "https://boards.greenhouse.io/adyen",
        "http://boards.greenhouse.io/adyen/",
        "https://boards.greenhouse.io/embed",
        "https://boards.greenhouse.io/picnic",
    ])
    assert slugs_from_text("greenhouse", text) == ["adyen", "picnic"]
    text = "https://Acme.recruitee.com/\nhttps://acme.recruitee.com\nhttps://careers-analytics.recruitee.com/\n"
    assert slugs_from_text("recruitee", text) == ["acme"]
    assert slugs_from_text("personio", "https://lepaya.jobs.personio.de/\n") == ["lepaya"]
    text = "https://nxp.wd3.myworkdayjobs.com/careers\nhttps://NXP.wd3.myworkdayjobs.com/en-US/careers/\n" \
           "https://acme.wd5.myworkdayjobs.com/wday\n"
    assert slugs_from_text("workday", text) == ["nxp.wd3/careers"]
