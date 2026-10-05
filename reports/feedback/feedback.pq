// Story 7.4 (FORM-240, AD-20): the Power Query (M) for the "feedback" table of the AI feedback
// semantic model. Paste it into Power Query's Advanced editor in the Power BI service (see README.md).
// Reads the nightly snapshot the feedback job writes (Story 7.3); signs in with an organizational
// account in formapp-feedback-readers. No customer data is in the file.
// FORM-240 follow-up: feedback-export moved to its own storage account, stsamplefbdemosea --
// Power BI records a source by account and test-lists every container on it when saving
// credentials, and the export container used to sit alongside the sign-in token store's private
// tokenstore container on the one account, which made that test reject the credentials.
let
    Source = AzureStorage.Blobs("stsamplefbdemosea"),
    Container = Source{[Name = "feedback-export"]}[Data],
    File = Container{[Name = "feedback.csv"]}[Content],
    Csv = Csv.Document(File, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(
        Promoted,
        {
            {"proposal_hash", type text},
            {"submitted_at", type datetimezone},
            {"product_code", type text},
            {"schema_version", Int64.Type},
            {"rating", Int64.Type},
            {"comment", type text},
            {"category", type text},
            {"agent_hash", type text}
        }
    ),
    // Submitted date in Malaysia time (UTC+8), for daily and weekly trends.
    WithDate = Table.AddColumn(
        Typed, "submitted_date",
        each DateTime.Date(DateTimeZone.SwitchZone([submitted_at], 8)), type date
    ),
    // Categories not assigned yet (a failed model call is retried the next night) show as "Pending".
    Categorised = Table.ReplaceValue(WithDate, null, "Pending", Replacer.ReplaceValue, {"category"})
in
    Categorised
